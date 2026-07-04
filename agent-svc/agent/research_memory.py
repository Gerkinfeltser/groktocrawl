"""Research Memory — Hybrid semantic cache using Valkey + Qdrant.

Stores research artifacts in Valkey with Qdrant-backed semantic similarity
search for cache retrieval.  Uses semantic-svc for embedding generation and
Qdrant directly for point CRUD operations.

Valkey key schema (ADR-0041):
    memory:{memory_id}:data  → JSON {query, artifact, sources, model,
                                      created_at, expires_at, user_id}
    memory:index             → SET of all active memory_ids

Qdrant collection: research_memory
    Point payload: {query, memory_id, user_id, timestamp, expires_at}

Config via env:
    RESEARCH_MEMORY_TTL (default 604800 = 7 days)
    RESEARCH_MEMORY_MAX_ARTIFACT_BYTES (default 5_242_880 = 5MB)
"""

import json
import logging
import os
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from redis import Redis

logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────
QDRANT_COLLECTION: str = "research_memory"
EMBED_DIM: int = 1024  # BAAI/bge-m3
DEFAULT_TTL: int = 604800  # 7 days
DEFAULT_MAX_ARTIFACT_BYTES: int = 5_242_880  # 5 MB
DEFAULT_SIMILARITY_THRESHOLD: float = 0.85


def _get_ttl() -> int:
    """TTL in seconds from RESEARCH_MEMORY_TTL env var, or default 7 days."""
    val = os.environ.get("RESEARCH_MEMORY_TTL", "")
    if val:
        try:
            return int(val)
        except ValueError:
            logger.warning(
                "Invalid RESEARCH_MEMORY_TTL=%s, using default %d",
                val,
                DEFAULT_TTL,
            )
    return DEFAULT_TTL


def _get_max_artifact_bytes() -> int:
    """Max artifact bytes from RESEARCH_MEMORY_MAX_ARTIFACT_BYTES, or 5 MB."""
    val = os.environ.get("RESEARCH_MEMORY_MAX_ARTIFACT_BYTES", "")
    if val:
        try:
            return int(val)
        except ValueError:
            logger.warning(
                "Invalid RESEARCH_MEMORY_MAX_ARTIFACT_BYTES=%s, using default %d",
                val,
                DEFAULT_MAX_ARTIFACT_BYTES,
            )
    return DEFAULT_MAX_ARTIFACT_BYTES


def _qdrant_url() -> str:
    """Qdrant URL from env or Docker default."""
    return os.environ.get("QDRANT_URL", "http://qdrant:6333").rstrip("/")


def _semantic_url() -> str:
    """Semantic service URL from env or Docker default."""
    return os.environ.get("SEMANTIC_URL", "http://semantic-svc:8003").rstrip("/")


class ResearchMemory:
    """Hybrid semantic cache for research artifacts.

    Valkey stores the full artifact payload (JSON blob with TTL).
    Qdrant stores the embedding vector + metadata for similarity search.
    Embedding generation is delegated to semantic-svc.

    Usage::

        memory = ResearchMemory(
            redis_url="redis://valkey:6379/0",
            semantic_url="http://semantic-svc:8003",
            qdrant_url="http://qdrant:6333",
        )
        # Store
        mid = await memory.store(prompt="...", artifact="...", sources=[...])
        # Query
        result = await memory.query(prompt="...")
        if result["hit"]:
            print(result["artifact"]["result"])
    """

    def __init__(
        self,
        redis_url: str,
        semantic_url: str | None = None,
        qdrant_url: str | None = None,
        threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
    ):
        """Initialise the memory store.

        Args:
            redis_url: Valkey connection string.
            semantic_url: semantic-svc base URL (for embeddings).  Falls
                back to ``SEMANTIC_URL`` env var then Docker default.
            qdrant_url: Qdrant base URL (for point CRUD).  Falls back
                to ``QDRANT_URL`` env var then Docker default.
            threshold: Minimum cosine similarity for a cache hit
                (default 0.85).
        """
        self.redis = Redis.from_url(redis_url, decode_responses=True)
        self._semantic_url = semantic_url or _semantic_url()
        self._qdrant_url = qdrant_url or _qdrant_url()
        self.threshold = threshold
        self.ttl = _get_ttl()
        self.max_artifact_bytes = _get_max_artifact_bytes()
        self._qdrant_client: httpx.AsyncClient | None = None
        self._semantic_client: httpx.AsyncClient | None = None

    # ── Internal HTTP clients ───────────────────────────────────

    async def _get_qdrant(self) -> httpx.AsyncClient:
        if self._qdrant_client is None:
            self._qdrant_client = httpx.AsyncClient(
                timeout=30,
                headers={"User-Agent": "GroktoCrawl/ResearchMemory"},
            )
        return self._qdrant_client

    async def _get_semantic(self) -> httpx.AsyncClient:
        if self._semantic_client is None:
            self._semantic_client = httpx.AsyncClient(
                timeout=30,
                headers={"User-Agent": "GroktoCrawl/ResearchMemory"},
            )
        return self._semantic_client

    async def close(self) -> None:
        """Close underlying HTTP clients."""
        if self._qdrant_client:
            await self._qdrant_client.aclose()
            self._qdrant_client = None
        if self._semantic_client:
            await self._semantic_client.aclose()
            self._semantic_client = None

    # ── Qdrant collection management ────────────────────────────

    async def _ensure_collection(self) -> None:
        """Ensure the *research_memory* collection exists in Qdrant."""
        qdrant = await self._get_qdrant()
        resp = await qdrant.get(f"{self._qdrant_url}/collections/{QDRANT_COLLECTION}")
        if resp.status_code == 200:
            return
        create_resp = await qdrant.put(
            f"{self._qdrant_url}/collections/{QDRANT_COLLECTION}",
            json={
                "vectors": {
                    "size": EMBED_DIM,
                    "distance": "Cosine",
                }
            },
        )
        if create_resp.status_code not in (200, 201):
            logger.warning(
                "Failed to create Qdrant collection %s: %s",
                QDRANT_COLLECTION,
                create_resp.text,
            )
        else:
            logger.info("Created Qdrant collection %s", QDRANT_COLLECTION)

    # ── Embedding via semantic-svc ──────────────────────────────

    async def _embed(self, text: str) -> list[float]:
        """Get an embedding vector for *text* via semantic-svc."""
        client = await self._get_semantic()
        resp = await client.post(
            f"{self._semantic_url}/embed",
            json={"input": [text]},
        )
        resp.raise_for_status()
        data = resp.json()
        return data["embeddings"][0]  # type: ignore[no-any-return]

    # ── Public API ──────────────────────────────────────────────

    async def query(
        self,
        prompt: str,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        """Search for a semantically similar cached artifact.

        Embeds *prompt* via semantic-svc, searches the Qdrant
        ``research_memory`` collection, fetches matching artifacts from
        Valkey, and returns the best match above the similarity
        threshold.

        Args:
            prompt: The research question to search for.
            user_id: Optional user scope for filtering.

        Returns:
            A dict with:
            - ``hit`` (bool)
            - ``artifact`` (dict | None)
            - ``similarity`` (float) — cosine similarity score
            - ``freshness`` (str | None) — ``fresh``, ``aging``, ``stale``
            - ``memory_id`` (str | None)
        """
        try:
            embedding = await self._embed(prompt)
        except Exception:
            logger.warning("Failed to embed query for research memory", exc_info=True)
            return {"hit": False}

        try:
            await self._ensure_collection()

            qdrant = await self._get_qdrant()
            search_payload: dict[str, Any] = {
                "vector": embedding,
                "limit": 5,
                "with_payload": True,
            }
            if user_id:
                search_payload["filter"] = {
                    "must": [{"key": "user_id", "match": {"value": user_id}}]
                }

            resp = await qdrant.post(
                f"{self._qdrant_url}/collections/{QDRANT_COLLECTION}/points/search",
                json=search_payload,
            )
            resp.raise_for_status()
            results = resp.json().get("result", [])
        except Exception:
            logger.warning("Qdrant search failed for research memory", exc_info=True)
            return {"hit": False}

        if not results:
            return {"hit": False}

        # Walk results in descending score order; first Valkey hit wins
        for result in results:
            score = float(result.get("score", 0))
            if score < self.threshold:
                logger.debug(
                    "Best Qdrant match below threshold: %.3f < %.2f",
                    score,
                    self.threshold,
                )
                return {"hit": False}

            payload = result.get("payload", {})
            memory_id = payload.get("memory_id", "")
            if not memory_id:
                continue

            artifact_raw = self.redis.get(f"memory:{memory_id}:data")
            if artifact_raw is None:
                # Valkey key expired — skip; sweep will clean it up later
                logger.debug("Valkey key missing for memory_id=%s, skipping", memory_id)
                continue

            try:
                artifact = json.loads(artifact_raw)
            except (json.JSONDecodeError, TypeError):
                logger.debug("Unparseable artifact for memory_id=%s", memory_id)
                continue

            # ── Freshness classification ────────────────────────
            created_at_str = artifact.get("created_at", "")
            try:
                created_at = datetime.fromisoformat(created_at_str)
            except (ValueError, TypeError):
                created_at = datetime.now(UTC)

            age_seconds = (datetime.now(UTC) - created_at).total_seconds()

            if age_seconds < self.ttl / 4:
                freshness = "fresh"
            elif age_seconds < self.ttl / 2:
                freshness = "aging"
            else:
                freshness = "stale"

            logger.info(
                "Research memory HIT for %r (similarity=%.3f, freshness=%s)",
                prompt[:80],
                score,
                freshness,
            )
            return {
                "hit": True,
                "artifact": artifact,
                "similarity": score,
                "freshness": freshness,
                "memory_id": memory_id,
            }

        return {"hit": False}

    async def store(
        self,
        prompt: str,
        artifact: str,
        sources: list[dict],
        model: str = "",
        user_id: str | None = None,
        metadata: dict | None = None,
    ) -> str:
        """Store a research artifact in the semantic cache.

        Writes to Valkey (``memory:{id}:data``, adds to ``memory:index``)
        and upserts a point in Qdrant with the embedded query vector.

        Args:
            prompt: The original research question.
            artifact: The LLM-synthesised answer (markdown).
            sources: List of source dicts (each with at minimum ``url``
                and ``title``).
            model: The LLM model that produced the artifact.
            user_id: Optional user scope.
            metadata: Optional extra context dict.

        Returns:
            The ``memory_id`` (UUID v4 string).
        """
        import uuid as _uuid

        memory_id = str(_uuid.uuid4())
        now = datetime.now(UTC)
        expires_at = now + timedelta(seconds=self.ttl)

        # Log warning if artifact exceeds size threshold
        artifact_bytes = len(artifact.encode("utf-8"))
        if artifact_bytes > self.max_artifact_bytes:
            logger.warning(
                "ResearchMemory artifact exceeds max size (%d > %d bytes) "
                "for memory_id=%s — storing anyway",
                artifact_bytes,
                self.max_artifact_bytes,
                memory_id,
            )

        # Build cache entry
        entry: dict[str, Any] = {
            "query": prompt,
            "artifact": artifact,
            "sources": sources,
            "model": model,
            "created_at": now.isoformat(),
            "expires_at": expires_at.isoformat(),
            "user_id": user_id,
        }
        if metadata:
            entry["metadata"] = metadata

        # Store in Valkey
        data_key = f"memory:{memory_id}:data"
        self.redis.set(data_key, json.dumps(entry), ex=self.ttl)
        self.redis.sadd("memory:index", memory_id)

        # Embed and store in Qdrant
        try:
            embedding = await self._embed(prompt)
            await self._ensure_collection()

            qdrant = await self._get_qdrant()
            point = {
                "id": memory_id,
                "vector": embedding,
                "payload": {
                    "query": prompt,
                    "memory_id": memory_id,
                    "user_id": user_id,
                    "timestamp": now.isoformat(),
                    "expires_at": expires_at.isoformat(),
                },
            }
            resp = await qdrant.put(
                f"{self._qdrant_url}/collections/{QDRANT_COLLECTION}/points",
                json={"points": [point]},
            )
            if resp.status_code not in (200, 201):
                logger.warning(
                    "Qdrant upsert returned %d for memory_id=%s: %s",
                    resp.status_code,
                    memory_id,
                    resp.text,
                )
            else:
                logger.info(
                    "Stored research memory %s (emb_dim=%d, sources=%d, "
                    "artifact_chars=%d)",
                    memory_id,
                    len(embedding),
                    len(sources),
                    len(artifact),
                )
        except Exception:
            logger.warning(
                "Failed to store Qdrant point for memory_id=%s "
                "(artifact stored in Valkey)",
                memory_id,
                exc_info=True,
            )

        return memory_id

    async def get(self, memory_id: str) -> dict | None:
        """Retrieve a research memory entry from Valkey by ID.

        Args:
            memory_id: The artifact ID returned by ``store()``.

        Returns:
            The stored dict or ``None`` if not found / expired.
        """
        raw = self.redis.get(f"memory:{memory_id}:data")
        if raw is None:
            return None
        try:
            return json.loads(raw)  # type: ignore[no-any-return]
        except (json.JSONDecodeError, TypeError):
            return None

    async def delete(self, memory_id: str) -> bool:
        """Delete from both Valkey **and** Qdrant atomically.

        Args:
            memory_id: The artifact ID to delete.

        Returns:
            ``True`` if the Valkey key existed and was deleted.
        """
        data_key = f"memory:{memory_id}:data"
        existed = self.redis.delete(data_key) > 0
        self.redis.srem("memory:index", memory_id)

        # Remove Qdrant point (best-effort)
        try:
            qdrant = await self._get_qdrant()
            resp = await qdrant.post(
                f"{self._qdrant_url}/collections/{QDRANT_COLLECTION}/points/delete",
                json={
                    "filter": {
                        "must": [{"key": "memory_id", "match": {"value": memory_id}}]
                    }
                },
            )
            if resp.status_code == 404:
                pass  # collection doesn't exist — nothing to do
            elif resp.status_code >= 400:
                logger.warning(
                    "Failed to delete Qdrant point for memory_id=%s: %s",
                    memory_id,
                    resp.text,
                )
            else:
                logger.info(
                    "Deleted research memory %s from Valkey + Qdrant", memory_id
                )
        except Exception:
            logger.warning(
                "Qdrant delete failed for memory_id=%s (Valkey already deleted)",
                memory_id,
                exc_info=True,
            )

        return existed

    async def sweep(self) -> int:
        """Remove Qdrant points whose Valkey keys have expired.

        Scrolls through all points in the ``research_memory`` Qdrant
        collection and deletes those with no corresponding
        ``memory:{id}:data`` Valkey key.

        Returns:
            Number of Qdrant points removed.
        """
        removed = 0

        try:
            qdrant = await self._get_qdrant()

            offset: str | None = None
            while True:
                scroll_payload: dict[str, Any] = {
                    "limit": 100,
                    "with_payload": True,
                }
                if offset:
                    scroll_payload["offset"] = offset

                resp = await qdrant.post(
                    f"{self._qdrant_url}/collections/{QDRANT_COLLECTION}/points/scroll",
                    json=scroll_payload,
                )

                if resp.status_code == 404:
                    # Collection doesn't exist — nothing to sweep
                    return 0

                resp.raise_for_status()
                data = resp.json()
                result_data = data.get("result", {})
                points = result_data.get("points", [])

                if not points:
                    break

                # Collect orphan IDs
                orphans: list[str] = []
                for point in points:
                    mid = point.get("payload", {}).get("memory_id", "")
                    if not mid:
                        continue
                    if not self.redis.exists(f"memory:{mid}:data"):
                        orphans.append(mid)

                # Delete each orphan
                for mid in orphans:
                    try:
                        del_resp = await qdrant.post(
                            f"{self._qdrant_url}/collections/{QDRANT_COLLECTION}"
                            "/points/delete",
                            json={
                                "filter": {
                                    "must": [
                                        {
                                            "key": "memory_id",
                                            "match": {"value": mid},
                                        }
                                    ]
                                }
                            },
                        )
                        if del_resp.status_code < 400:
                            removed += 1
                    except Exception:
                        logger.debug("Failed to delete orphan Qdrant point %s", mid)

                next_offset = result_data.get("next_page_offset")
                if next_offset:
                    offset = next_offset
                else:
                    break

            if removed:
                logger.info(
                    "Swept %d orphaned Qdrant points from research_memory",
                    removed,
                )
        except Exception:
            logger.warning("Research memory sweep failed", exc_info=True)

        return removed
