"""Research Memory — cross-session semantic cache for research artifacts.

Stores research results in Valkey with embedded question vectors for
semantic similarity lookup.  Uses the same BAAI/bge-m3 embedding model
as semantic-svc so that cached artifacts can be retrieved by meaning,
not just exact text match.

Key schema::

    research:mem:{artifact_id}  → JSON {question, answer, sources,
                                        embedding, created_at, metadata}

TTL: 72 hours (259200 seconds) by default.
"""

import json
import logging
import uuid
from datetime import UTC, datetime, timedelta

import numpy as np
from redis import Redis

logger = logging.getLogger(__name__)

# Lazy-loaded embedding model — loaded on first use to avoid startup
# cost when research memory is never used.
_embed_model: object | None = None
EMBED_MODEL_NAME: str = "BAAI/bge-m3"
DEFAULT_TTL: int = 259200  # 72 hours


def _load_embed_model() -> object:
    """Load the SentenceTransformer model on first use.

    Returns:
        A SentenceTransformer instance configured for BAAI/bge-m3
        with L2-normalized output vectors.
    """
    global _embed_model
    if _embed_model is None:
        from sentence_transformers import SentenceTransformer

        logger.info("Loading embedding model %s for research memory...", EMBED_MODEL_NAME)
        _embed_model = SentenceTransformer(EMBED_MODEL_NAME)
        logger.info("Embedding model %s loaded.", EMBED_MODEL_NAME)
    return _embed_model


def _embed(text: str) -> list[float]:
    """Embed a single text string into a normalized 1024-dim vector.

    Args:
        text: The text to embed (typically a research question).

    Returns:
        A list of 1024 floats representing the L2-normalized embedding.
    """
    model = _load_embed_model()
    embedding: np.ndarray = model.encode(  # type: ignore[union-attr]
        [text], normalize_embeddings=True
    )
    return embedding[0].tolist()


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two L2-normalized vectors.

    Since both vectors are already normalized to unit length, the dot
    product is equivalent to the cosine similarity.

    Args:
        a: First normalized vector (list of floats).
        b: Second normalized vector (list of floats).

    Returns:
        Cosine similarity in [0, 1] range (embeddings from BGE-M3 are
        non-negative after normalization).
    """
    return float(np.dot(a, b))


_FRESH_THRESHOLD: float = 1.0 / 3.0  # age < 1/3 of max_age → fresh
_AGING_THRESHOLD: float = 2.0 / 3.0  # age < 2/3 of max_age → aging


class ResearchMemory:
    """Cross-session semantic cache for agent research artifacts.

    Stores research results in Valkey with embedded question vectors.
    On query, scans stored artifacts and returns the most semantically
    similar result if above a configurable cosine-similarity threshold.

    Usage::

        memory = ResearchMemory("redis://valkey:6379/0")
        memory.store(
            question="What is the EU AI Act?",
            answer="The EU AI Act is ...",
            sources=[{"url": "https://...", "title": "..."}],
            metadata={"model": "gpt-4o"},
        )
        result = memory.query("Tell me about EU AI regulation")
        if result["hit"]:
            print(result["artifact"]["answer"])
    """

    def __init__(self, redis_url: str, threshold: float = 0.85):
        """Initialize the research memory store.

        Args:
            redis_url: Valkey/Redis connection URL
                (e.g., ``"redis://valkey:6379/0"``).
            threshold: Minimum cosine similarity for a cache hit
                (default 0.85).  Values closer to 1.0 are stricter.
        """
        self.redis = Redis.from_url(redis_url, decode_responses=True)
        self.threshold = threshold

    # ── Public API ────────────────────────────────────────────────

    def store(
        self,
        question: str,
        answer: str,
        sources: list[dict],
        metadata: dict | None = None,
    ) -> str:
        """Embed the question and store the research artifact in Valkey.

        The artifact is stored under ``research:mem:{artifact_id}`` with
        a default TTL of 72 hours.  Embeddings are stored as a JSON list
        inside the artifact blob so no external vector store is required.

        Args:
            question: The original research question (used for embedding).
            answer: The LLM-synthesised answer (markdown).
            sources: List of source dicts, each with at minimum ``url``
                and ``title``.
            metadata: Optional dict with extra context (model used,
                user_id, etc.).

        Returns:
            The artifact ID (UUID v4 string).
        """
        artifact_id = str(uuid.uuid4())
        now = datetime.now(UTC).isoformat()
        embedding = _embed(question)

        artifact = {
            "question": question,
            "answer": answer,
            "sources": sources,
            "embedding": embedding,
            "created_at": now,
            "metadata": metadata or {},
        }

        key = f"research:mem:{artifact_id}"
        self.redis.set(key, json.dumps(artifact), ex=DEFAULT_TTL)
        logger.info(
            "Stored research memory artifact %s (%d sources, %d chars answer)",
            artifact_id,
            len(sources),
            len(answer),
        )
        return artifact_id

    def query(
        self,
        question: str,
        max_age_hours: int = 72,
    ) -> dict:
        """Search for a semantically similar cached research artifact.

        Embeds the question and scans all stored artifacts in Valkey,
        computing cosine similarity against each.  Returns the best
        match above the configured threshold, or ``{"hit": False}``
        if nothing matches.

        Args:
            question: The research question to search for.
            max_age_hours: Maximum age (in hours) of artifacts to
                consider.  Older artifacts are skipped.  Default 72 h.

        Returns:
            A dict with:
            - ``hit`` (bool): Whether a match was found.
            - ``artifact`` (dict | None): The full artifact if ``hit``
              is True.
            - ``age_hours`` (float | None): Age of the artifact in hours.
            - ``freshness`` (str | None): ``"fresh"``, ``"aging"``, or
              ``"stale"``.
        """
        query_embedding = _embed(question)
        now = datetime.now(UTC)
        best_similarity: float = 0.0
        best_artifact: dict | None = None
        best_age_hours: float = 0.0

        # Scan all research memory keys
        cursor: int = 0
        while True:
            cursor, keys = self.redis.scan(
                cursor=cursor,
                match="research:mem:*",
                count=100,
            )
            if keys:
                pipe = self.redis.pipeline()
                for key in keys:
                    pipe.get(key)
                results = pipe.execute()
                for raw in results:
                    if raw is None:
                        continue
                    try:
                        artifact = json.loads(raw)
                    except (json.JSONDecodeError, TypeError):
                        logger.debug("Skipping unparseable artifact at key (value: %s...)", str(raw)[:100])
                        continue

                    stored_embedding = artifact.get("embedding")
                    if not stored_embedding or not isinstance(stored_embedding, list):
                        continue

                    # Age check
                    created_at_str = artifact.get("created_at", "")
                    try:
                        created_at = datetime.fromisoformat(created_at_str)
                    except (ValueError, TypeError):
                        continue
                    age_hours = (now - created_at).total_seconds() / 3600.0
                    if age_hours > max_age_hours:
                        continue

                    similarity = _cosine_similarity(query_embedding, stored_embedding)
                    if similarity > best_similarity:
                        best_similarity = similarity
                        best_artifact = artifact
                        best_age_hours = age_hours

            if cursor == 0:
                break

        if best_similarity < self.threshold or best_artifact is None:
            logger.debug(
                "Research memory miss for %r (best similarity: %.3f, threshold: %.2f)",
                question[:80],
                best_similarity,
                self.threshold,
            )
            return {"hit": False}

        # Determine freshness
        freshness: str
        if best_age_hours < max_age_hours * _FRESH_THRESHOLD:
            freshness = "fresh"
        elif best_age_hours < max_age_hours * _AGING_THRESHOLD:
            freshness = "aging"
        else:
            freshness = "stale"

        logger.info(
            "Research memory HIT for %r (similarity: %.3f, age: %.1fh, freshness: %s)",
            question[:80],
            best_similarity,
            best_age_hours,
            freshness,
        )
        return {
            "hit": True,
            "artifact": best_artifact,
            "age_hours": round(best_age_hours, 2),
            "freshness": freshness,
        }

    def delete(self, artifact_id: str) -> bool:
        """Delete a research memory artifact by ID.

        Args:
            artifact_id: The artifact ID returned by ``store()``.

        Returns:
            ``True`` if the artifact existed and was deleted, ``False``
            if it was not found.
        """
        key = f"research:mem:{artifact_id}"
        deleted = self.redis.delete(key)
        if deleted:
            logger.info("Deleted research memory artifact %s", artifact_id)
        else:
            logger.debug("Research memory artifact %s not found for deletion", artifact_id)
        return deleted > 0

    def cleanup(self) -> int:
        """Explicitly remove expired artifacts.

        Note: Valkey automatically evicts keys when their TTL expires,
        so this method is a belt-and-suspenders cleanup for cases where
        the TTL has not yet fired but the artifact is past its intended
        lifespan.

        Returns:
            Number of artifacts removed.
        """
        removed = 0
        now = datetime.now(UTC)
        max_age = timedelta(seconds=DEFAULT_TTL)
        cursor: int = 0
        while True:
            cursor, keys = self.redis.scan(
                cursor=cursor,
                match="research:mem:*",
                count=100,
            )
            if keys:
                pipe = self.redis.pipeline()
                for key in keys:
                    pipe.get(key)
                results = pipe.execute()
                for key, raw in zip(keys, results):
                    if raw is None:
                        continue
                    try:
                        artifact = json.loads(raw)
                    except (json.JSONDecodeError, TypeError):
                        # Unparseable — delete it
                        self.redis.delete(key)
                        removed += 1
                        continue

                    created_at_str = artifact.get("created_at", "")
                    try:
                        created_at = datetime.fromisoformat(created_at_str)
                    except (ValueError, TypeError):
                        # Bad timestamp — delete
                        self.redis.delete(key)
                        removed += 1
                        continue

                    if now - created_at > max_age:
                        self.redis.delete(key)
                        removed += 1
            if cursor == 0:
                break

        if removed:
            logger.info("Cleaned up %d expired research memory artifacts", removed)
        return removed
