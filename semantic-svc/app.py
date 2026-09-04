"""Semantic search service — embedding, reranking, and vector index.

Phase 1 endpoints (existing):
- POST /embed — vectorize query and document texts via BGE-M3
- POST /rerank — cross-encode query against documents via BGE-reranker-v2-m3

Phase 2 endpoints:
- POST /index — embed and store a page in the persistent vector index
- POST /search/vector — query the vector index by semantic similarity
- DELETE /index/{url_hash} — remove a page from the index
- GET /index/stats — index size and configuration

Phase 3 endpoints:
- Retention scoring, domain classification, access tracking (see ADR-0027)

Phase 4 endpoints (this file):
- GET /index/model — current embedding model config and migration state
- POST /index/migrate/start — start embedding model migration
- GET /index/migrate/status — migration progress
- POST /index/migrate/cutover — switch to new model
|- Named vector support for multi-model coexistence (see ADR-0028)
|
|Observability (ADR-0029):
|- GET /metrics — Prometheus-compatible OpenMetrics endpoint (stdlib, no deps)
"""

from __future__ import annotations

import asyncio
import contextlib
import datetime
import hashlib
import logging
import math
import os
import time
from collections.abc import Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import numpy as np
from auth import verify_api_key
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from metrics import METRICS
from models import (
    EmbedRequest,
    EmbedResponse,
    RerankRequest,
    RerankResponse,
    RerankResult,
)
from qdrant_client import QdrantClient, models

if TYPE_CHECKING:
    from sentence_transformers import CrossEncoder, SentenceTransformer

from common.logging import setup_logging
from common.middleware import add_request_id_middleware

setup_logging()
logger = logging.getLogger(__name__)


def _load_sentence_transformers():
    """Import model classes only when semantic inference is used."""
    from sentence_transformers import CrossEncoder, SentenceTransformer

    return CrossEncoder, SentenceTransformer


# ── TaskTracker (copied from agent-svc; avoids cross-service import) ──


class TaskTracker:
    """Tracks background tasks for graceful shutdown."""

    def __init__(self) -> None:
        self._tasks: set[asyncio.Task] = set()
        self._shutdown_event = asyncio.Event()

    def create_background_task(self, coro) -> asyncio.Task:
        """Create, track, and return a background task."""
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    @property
    def shutdown_requested(self) -> bool:
        return self._shutdown_event.is_set()

    async def shutdown(self, grace_period: float = 5.0) -> None:
        """Signal shutdown, cancel tracked tasks after grace period."""
        self._shutdown_event.set()
        if not self._tasks:
            return

        logger.info(
            "Shutting down %d background tasks (grace=%ss)",
            len(self._tasks),
            grace_period,
        )

        _, pending = await asyncio.wait(self._tasks, timeout=grace_period)

        if pending:
            logger.warning(
                "Cancelling %d tasks after %ss grace period",
                len(pending),
                grace_period,
            )
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)


# ── Bounded native inference execution ────────────────────────────


def _positive_int_env(name: str, default: int, *, minimum: int = 1) -> int:
    """Read a bounded integer setting and fail fast on invalid deployment config."""
    value = int(os.getenv(name, str(default)))
    if value < minimum:
        raise ValueError(f"{name} must be >= {minimum}")
    return value


def _nonnegative_int_env(name: str, default: int) -> int:
    """Read a queue-size setting that may be zero (no waiting queue)."""
    value = int(os.getenv(name, str(default)))
    if value < 0:
        raise ValueError(f"{name} must be >= 0")
    return value


INFERENCE_WORKERS = _positive_int_env("SEMANTIC_INFERENCE_WORKERS", 1)
INFERENCE_QUEUE_SIZE = _nonnegative_int_env("SEMANTIC_INFERENCE_QUEUE_SIZE", 16)
INFERENCE_ADMISSION_TIMEOUT = float(
    os.getenv("SEMANTIC_INFERENCE_ADMISSION_TIMEOUT_SECONDS", "0.25")
)
if INFERENCE_ADMISSION_TIMEOUT <= 0:
    raise ValueError("SEMANTIC_INFERENCE_ADMISSION_TIMEOUT_SECONDS must be > 0")

_INFERENCE_OPERATIONS = frozenset(
    {
        "rerank",
        "embed",
        "vector_search",
        "index",
        "index_batch",
        "migration_backfill",
    }
)
_INFERENCE_PRIORITIES = {"interactive": 0, "maintenance": 10}


class InferenceOverloadedError(Exception):
    """Raised when bounded inference admission cannot accept a request."""

    def __init__(self, operation: str, retry_after: float) -> None:
        self.operation = operation
        self.retry_after = retry_after
        super().__init__(f"semantic inference capacity exhausted for {operation}")


# Short compatibility name for callers that want to catch admission overloads.
InferenceOverloaded = InferenceOverloadedError


@dataclass
class _InferenceWork:
    """One admitted native call and its result future."""

    operation: str
    priority: int
    function: Callable[[], Any]
    result: asyncio.Future[Any]
    admitted_at: float
    abandoned: bool = False
    native_started: bool = False
    sequence: int = field(default=0)


class InferenceManager:
    """Run model calls in a bounded, priority-aware native worker pool.

    The semaphore bounds both active calls and queued calls. Native futures are
    awaited by manager-owned workers, so cancellation of an HTTP task never
    releases a capacity slot while a blocking model call is still running.
    """

    def __init__(
        self,
        *,
        max_workers: int = INFERENCE_WORKERS,
        queue_size: int = INFERENCE_QUEUE_SIZE,
        admission_timeout: float = INFERENCE_ADMISSION_TIMEOUT,
    ) -> None:
        if max_workers < 1:
            raise ValueError("max_workers must be >= 1")
        if queue_size < 0:
            raise ValueError("queue_size must be >= 0")
        if admission_timeout <= 0:
            raise ValueError("admission_timeout must be > 0")
        self.max_workers = max_workers
        self.queue_size = queue_size
        self.admission_timeout = admission_timeout
        self._capacity = asyncio.Semaphore(max_workers + queue_size)
        self._queue: asyncio.PriorityQueue[tuple[int, int, _InferenceWork | None]] = (
            asyncio.PriorityQueue()
        )
        self._workers: list[asyncio.Task[None]] = []
        self._loop: asyncio.AbstractEventLoop | None = None
        self._sequence = 0
        self._closed = False
        self._queued = 0
        self._in_flight = 0

    @staticmethod
    def _operation_name(operation: str) -> str:
        return operation if operation in _INFERENCE_OPERATIONS else "other"

    def _observe_queue_depth(self) -> None:
        METRICS.gauge(
            "groktocrawl_semantic_inference_queue_depth",
            "Number of admitted model calls waiting for a native worker",
        ).set(value=float(self._queued))

    def _observe_in_flight(self) -> None:
        METRICS.gauge(
            "groktocrawl_semantic_inference_in_flight",
            "Number of native model calls currently running",
        ).set(value=float(self._in_flight))

    async def _ensure_started(self) -> None:
        if self._closed:
            raise InferenceOverloadedError("other", self.admission_timeout)
        loop = asyncio.get_running_loop()
        if self._loop is not None and self._loop is not loop:
            # Direct unit callers may use asyncio.run repeatedly. Production
            # lifespan uses one loop; reset only an idle manager between loops.
            if self._in_flight or self._queued:
                raise InferenceOverloadedError("other", self.admission_timeout)
            self._workers = []
            self._capacity = asyncio.Semaphore(self.max_workers + self.queue_size)
            self._queue = asyncio.PriorityQueue()
        self._loop = loop
        if not self._workers:
            self._workers = [
                asyncio.create_task(self._worker()) for _ in range(self.max_workers)
            ]

    async def run(
        self,
        operation: str,
        function: Callable[[], Any],
        *,
        priority: str = "interactive",
    ) -> Any:
        """Admit and execute one blocking model call.

        ``asyncio.shield`` deliberately prevents cancellation from propagating
        to the manager-owned result future. The native call therefore remains
        accounted for until it actually returns or raises.
        """
        operation = self._operation_name(operation)
        priority_value = _INFERENCE_PRIORITIES.get(priority, 0)
        await self._ensure_started()
        admission_start = time.monotonic()
        try:
            await asyncio.wait_for(
                self._capacity.acquire(), timeout=self.admission_timeout
            )
        except TimeoutError as exc:
            METRICS.counter(
                "groktocrawl_semantic_inference_overloads_total",
                "Model calls rejected after bounded admission timeout",
                ["operation"],
            ).inc({"operation": operation})
            raise InferenceOverloadedError(operation, self.admission_timeout) from exc

        if self._closed:
            self._capacity.release()
            raise InferenceOverloadedError(operation, self.admission_timeout)

        loop = asyncio.get_running_loop()
        item = _InferenceWork(
            operation=operation,
            priority=priority_value,
            function=function,
            result=loop.create_future(),
            admitted_at=admission_start,
            sequence=self._sequence,
        )
        self._sequence += 1
        self._queued += 1
        self._observe_queue_depth()
        self._queue.put_nowait((item.priority, item.sequence, item))
        try:
            return await asyncio.shield(item.result)
        except asyncio.CancelledError:
            # The manager worker continues to own the slot and native future.
            item.abandoned = True
            METRICS.counter(
                "groktocrawl_semantic_inference_cancellations_total",
                "HTTP callers canceled while model inference was admitted",
                ["operation"],
            ).inc({"operation": operation})
            raise

    async def _worker(self) -> None:
        while True:
            if self._closed and self._queue.empty():
                return
            _, _, item = await self._queue.get()
            if item is None:
                self._queue.task_done()
                return
            self._queued -= 1
            self._observe_queue_depth()
            if item.abandoned:
                self._capacity.release()
                self._queue.task_done()
                continue

            queue_wait = time.monotonic() - item.admitted_at
            METRICS.histogram(
                "groktocrawl_semantic_inference_queue_wait_seconds",
                "Time spent admitted before native model execution",
                ["operation", "priority"],
            ).observe(
                {
                    "operation": item.operation,
                    "priority": "maintenance" if item.priority else "interactive",
                },
                queue_wait,
            )
            item.native_started = True
            self._in_flight += 1
            self._observe_in_flight()
            native_start = time.monotonic()
            try:
                # The manager owns exactly ``max_workers`` worker tasks. The
                # loop's executor is used so asyncio.run can drain it during
                # test/process shutdown; admission still bounds native calls.
                loop = asyncio.get_running_loop()
                result = await loop.run_in_executor(None, item.function)
            except BaseException as exc:
                if not item.abandoned and not item.result.done():
                    item.result.set_exception(exc)
                if not isinstance(exc, asyncio.CancelledError):
                    METRICS.counter(
                        "groktocrawl_semantic_inference_failures_total",
                        "Native model calls that raised an exception",
                        ["operation"],
                    ).inc({"operation": item.operation})
            else:
                if not item.abandoned and not item.result.done():
                    item.result.set_result(result)
            finally:
                METRICS.histogram(
                    "groktocrawl_semantic_inference_duration_seconds",
                    "Native model inference latency",
                    ["operation"],
                ).observe(
                    {"operation": item.operation}, time.monotonic() - native_start
                )
                self._in_flight -= 1
                self._observe_in_flight()
                self._capacity.release()
                self._queue.task_done()

    async def shutdown(self) -> None:
        """Reject queued work, drain native calls, then close the executor."""
        if self._closed:
            return
        self._closed = True
        while not self._queue.empty():
            _, _, item = self._queue.get_nowait()
            if item is None:
                self._queue.task_done()
                continue
            self._queued -= 1
            item.abandoned = True
            if not item.result.done():
                item.result.cancel()
            self._capacity.release()
            self._queue.task_done()
        self._observe_queue_depth()
        if self._workers:
            # Wake idle workers. Active workers finish their native call first,
            # then consume one sentinel each and exit.
            for _ in self._workers:
                self._queue.put_nowait((100, self._sequence, None))
                self._sequence += 1
            await asyncio.gather(*self._workers, return_exceptions=True)


_inference_manager = InferenceManager()


def _get_inference_manager() -> InferenceManager:
    return _inference_manager


async def run_inference(
    operation: str,
    function: Callable[[], Any],
    *,
    priority: str = "interactive",
) -> Any:
    """Execute a model call through the process-wide bounded inference pool."""
    return await _get_inference_manager().run(operation, function, priority=priority)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Load SentenceTransformer and CrossEncoder models at startup."""
    global _embed_model, _rerank_model, _models_ready, _inference_manager
    app.state.task_tracker = TaskTracker()
    # A fresh manager is tied to this event loop. Its workers drain native
    # calls before the executor is closed during shutdown.
    _inference_manager = InferenceManager()
    app.state.inference_manager = _inference_manager
    logger.info("Loading semantic models (~2.2GB, 2-5s)...")
    loop = asyncio.get_event_loop()
    try:
        cross_encoder_cls, sentence_transformer_cls = _load_sentence_transformers()
        _embed_model = await loop.run_in_executor(
            None, lambda: sentence_transformer_cls(EMBED_MODEL_NAME)
        )
        _rerank_model = await loop.run_in_executor(
            None, lambda: cross_encoder_cls(RERANK_MODEL_NAME)
        )
        _models_ready = True
        logger.info("Models loaded — semantic-svc ready")
    except Exception:
        logger.exception(
            "Failed to load semantic models — /health will report 'starting'"
        )
    yield
    await app.state.task_tracker.shutdown(grace_period=5.0)
    _models_ready = False
    _embed_model = None
    _rerank_model = None
    await _inference_manager.shutdown()


app = FastAPI(title="semantic-svc", lifespan=lifespan)


@app.exception_handler(InferenceOverloaded)
async def inference_overloaded_handler(
    request: Request, exc: InferenceOverloaded
) -> JSONResponse:
    """Return a retryable overload response without exposing model internals."""
    del request
    return JSONResponse(
        status_code=503,
        content={
            "detail": "Semantic inference capacity is temporarily unavailable",
            "error": "inference_overloaded",
            "operation": exc.operation,
        },
        headers={"Retry-After": str(max(1, math.ceil(exc.retry_after)))},
    )


# ── Instrumentation ──────────────────────────────────────────
add_request_id_middleware(
    app,
    record_metric=lambda labels, val: METRICS.histogram(
        "http_request_duration_seconds",
        "HTTP request latency by path and method",
        ["method", "path"],
    ).observe(labels, val),
)

# ── Model config ──────────────────────────────────────────────────
# Configurable via env vars so embedding models can be swapped
# without code changes.
EMBED_MODEL_NAME = os.getenv("EMBED_MODEL_NAME", "BAAI/bge-m3")
EMBED_DIM = int(os.getenv("EMBED_DIM", "1024"))
RERANK_MODEL_NAME = "BAAI/bge-reranker-v2-m3"

# Active named vector: which model produces vectors for indexing
# and queries. Must match a named vector in the Qdrant collection.
# Named vector convention: v_{model_short} (e.g., v_bge-m3, v_bge-m4)
ACTIVE_EMBED_MODEL = os.getenv("ACTIVE_EMBED_MODEL", "bge-m3")

_embed_model: SentenceTransformer | None = None
_rerank_model: CrossEncoder | None = None
_models_ready: bool = False
_qdrant: QdrantClient | None = None
_qdrant_ready: bool = False

COLLECTION_NAME = "groktocrawl_pages"
MAX_DOCS = int(os.getenv("VECTOR_INDEX_MAX_DOCS", "250000"))
QDRANT_URL = os.getenv("QDRANT_URL", "http://qdrant:6333")
QDRANT_QUERY_TIMEOUT = float(os.getenv("QDRANT_QUERY_TIMEOUT", "10"))
# Client-side timeout for the blocking Qdrant HTTP calls. Defaults to
# QDRANT_QUERY_TIMEOUT so the asyncio.wait_for wrapper in router_search
# stays the binding bound — a lower hardcoded client timeout (the old 5s)
# would fire first and make slow-but-healthy indexes unreachable (issue #588).
# Rounded UP (ceil) to satisfy qdrant-client's int-typed timeout without ever
# landing below the fractional wrapper timeout (int() truncation would).
QDRANT_CLIENT_TIMEOUT = math.ceil(
    float(os.getenv("QDRANT_CLIENT_TIMEOUT", str(QDRANT_QUERY_TIMEOUT)))
)

# ── Migration state (in-memory, lost on restart) ──────────────────
# For restart-surviving state, store in Valkey or a known Qdrant point.
_migration = {
    "status": "idle",  # idle | backfilling | dual_write | cutover | complete
    "source_model": EMBED_MODEL_NAME,
    "source_dim": EMBED_DIM,
    "target_model": "",
    "target_dim": 0,
    "docs_processed": 0,
    "docs_total": 0,
    "started_at": "",
    "completed_at": "",
}
_migration_task: asyncio.Task | None = None

# In-memory override for active model (set by /migrate/cutover;
# resets to ACTIVE_EMBED_MODEL env var on restart).
_active_override: str | None = None


def _get_active_model() -> str:
    """Return the effective active named vector.

    Prefers the in-memory override (set by cutover), falling back
    to the ACTIVE_EMBED_MODEL env var.
    """
    return _active_override if _active_override is not None else ACTIVE_EMBED_MODEL


def _set_active_override(val: str | None) -> None:
    """Set the in-memory active model override (used by migration cutover)."""
    global _active_override
    _active_override = val


# ── Target model cache for migration dual-write ────────────────────
# Cached globally so that batch dual-write does not instantiate a new
# SentenceTransformer per page (see fix-semantic-hardening).

_target_embed_model: SentenceTransformer | None = None
_target_embed_model_name: str = ""


async def _get_target_embed_model(target_name: str) -> SentenceTransformer:
    """Get or load the target embedding model for migration dual-write.

    Caches the model globally so that batch dual-write (which can process
    hundreds of pages in a single request) does not re-instantiate the
    SentenceTransformer for each page.
    """
    global _target_embed_model, _target_embed_model_name
    if _target_embed_model is None or _target_embed_model_name != target_name:
        _, sentence_transformer_cls = _load_sentence_transformers()
        loop = asyncio.get_event_loop()
        _target_embed_model = await loop.run_in_executor(
            None, lambda: sentence_transformer_cls(target_name)
        )
        _target_embed_model_name = target_name
    return _target_embed_model


def _set_migration_task(task: asyncio.Task | None) -> None:
    """Set the migration background task reference."""
    global _migration_task
    _migration_task = task


# ── Model helpers ─────────────────────────────────────────────────


def _get_embed_model() -> SentenceTransformer:
    return _embed_model


def _get_rerank_model() -> CrossEncoder:
    return _rerank_model


def _url_hash(url: str) -> int:
    """Deterministic point ID from URL — first 64 bits of SHA-256 as uint64."""
    h = hashlib.sha256(url.encode()).hexdigest()
    return int(h[:16], 16)


def _is_qdrant_ready() -> bool:
    """Return whether Qdrant is reachable without initializing the collection."""
    client = _qdrant
    temporary_client = client is None
    if temporary_client:
        client = QdrantClient(url=QDRANT_URL, timeout=QDRANT_CLIENT_TIMEOUT)
    assert client is not None
    try:
        client.get_collections()
    except Exception:
        return False
    finally:
        if temporary_client:
            with contextlib.suppress(Exception):
                client.close()
    return True


def _named_vector_name(model_name: str) -> str:
    """Short name for a named vector (e.g., 'BAAI/bge-m3' -> 'v_bge-m3')."""
    short = model_name.split("/")[-1].lower()
    # Replace non-alphanumeric chars with hyphens for Qdrant compatibility
    short = "".join(c if c.isalnum() else "-" for c in short).strip("-")
    return f"v_{short}"


def _now_iso() -> str:
    """Return current UTC timestamp as ISO 8601 string."""
    return datetime.datetime.now(datetime.UTC).isoformat()


async def _ensure_qdrant() -> QdrantClient:
    """Lazy-init Qdrant client and collection with named vector support."""
    global _qdrant, _qdrant_ready
    if _qdrant is None:
        _qdrant = QdrantClient(url=QDRANT_URL, timeout=QDRANT_CLIENT_TIMEOUT)
    if not _qdrant_ready:
        try:
            collections = _qdrant.get_collections()
            if COLLECTION_NAME not in [c.name for c in collections.collections]:
                # Create collection with a single named vector for the active model
                nv_name = _named_vector_name(EMBED_MODEL_NAME)
                _qdrant.create_collection(
                    collection_name=COLLECTION_NAME,
                    vectors_config={
                        nv_name: models.VectorParams(
                            size=EMBED_DIM,
                            distance=models.Distance.COSINE,
                        ),
                    },
                )
                logger.info(
                    "Created Qdrant collection '%s' with named vector '%s' (dim=%d)",
                    COLLECTION_NAME,
                    nv_name,
                    EMBED_DIM,
                )
            else:
                # Validate that the active named vector exists in the collection
                info = _qdrant.get_collection(COLLECTION_NAME)
                configured_vectors = info.config.params.vectors
                if isinstance(configured_vectors, dict):
                    nv_name = _named_vector_name(EMBED_MODEL_NAME)
                    if nv_name not in configured_vectors:
                        # Legacy collection (no named vectors) — migrate
                        logger.info(
                            "Legacy collection detected (no named vectors). "
                            "Migrating... deleting and recreating '%s' with named vector '%s'.",
                            COLLECTION_NAME,
                            nv_name,
                        )
                        # Qdrant cannot add named vectors post-creation. Delete and recreate.
                        _qdrant.delete_collection(COLLECTION_NAME)
                        _qdrant.create_collection(
                            collection_name=COLLECTION_NAME,
                            vectors_config={
                                nv_name: models.VectorParams(
                                    size=EMBED_DIM,
                                    distance=models.Distance.COSINE,
                                ),
                            },
                        )
                        logger.info(
                            "Recreated '%s' with named vector '%s'",
                            COLLECTION_NAME,
                            nv_name,
                        )
                elif not isinstance(configured_vectors, dict):
                    # Flat vector config — migrate to named vectors
                    nv_name = _named_vector_name(EMBED_MODEL_NAME)
                    logger.info(
                        "Legacy flat-vector collection detected. "
                        "Migrating to named vector '%s'...",
                        nv_name,
                    )
                    _qdrant.delete_collection(COLLECTION_NAME)
                    _qdrant.create_collection(
                        collection_name=COLLECTION_NAME,
                        vectors_config={
                            nv_name: models.VectorParams(
                                size=EMBED_DIM,
                                distance=models.Distance.COSINE,
                            ),
                        },
                    )
                    logger.info(
                        "Recreated '%s' with named vector '%s'",
                        COLLECTION_NAME,
                        nv_name,
                    )
            _qdrant_ready = True
        except Exception as e:
            logger.error("Qdrant init failed: %s", e)
            raise HTTPException(503, "Vector index unavailable")
    return _qdrant


# ── Metrics middleware ──────────────────────────────────────────────


@app.middleware("http")
async def metrics_middleware(request: Request, call_next):
    """Record request count and duration for all endpoints except /metrics."""
    path = request.url.path
    if path == "/metrics":
        return await call_next(request)

    start = time.time()
    try:
        response = await call_next(request)
        return response
    finally:
        duration = time.time() - start
        METRICS.counter(
            "groktocrawl_search_requests_total",
            "Total requests by endpoint",
            ["endpoint"],
        ).inc({"endpoint": path})
        METRICS.histogram(
            "groktocrawl_index_query_duration_seconds",
            "Request latency by endpoint",
            ["endpoint"],
        ).observe({"endpoint": path}, duration)


# ── Core endpoints ──────────────────────────────────────────────────


@app.get("/health")
async def health():
    if not _models_ready:
        return {"status": "starting", "models": "loading"}

    loop = asyncio.get_running_loop()
    qdrant_ready = await loop.run_in_executor(None, _is_qdrant_ready)
    return {
        "status": "ok" if qdrant_ready else "starting",
        "models": "loaded",
        "qdrant": "ready" if qdrant_ready else "unavailable",
    }


@app.post("/embed", response_model=EmbedResponse)
async def embed(body: EmbedRequest):
    """Embed one or more texts into normalized vectors."""
    if not _models_ready:
        raise HTTPException(
            503, "Models are still loading — please retry in a few seconds"
        )
    model = _get_embed_model()
    embed_start = time.time()
    embeddings = await run_inference(
        "embed",
        lambda: model.encode(body.input, normalize_embeddings=True),
    )
    embeddings_list = embeddings.tolist()
    embed_duration = time.time() - embed_start
    METRICS.histogram(
        "groktocrawl_index_embeddings_duration_seconds",
        "Embedding model inference latency",
    ).observe({}, embed_duration)
    return EmbedResponse(embeddings=embeddings_list)


@app.post("/rerank", response_model=RerankResponse)
async def rerank(body: RerankRequest):
    """Cross-encode a query against documents, returning top-k."""
    if not _models_ready:
        raise HTTPException(
            503, "Models are still loading — please retry in a few seconds"
        )
    model = _get_rerank_model()
    pairs = [[body.query, doc] for doc in body.documents]
    scores = await run_inference("rerank", lambda: model.predict(pairs))
    indices = np.argsort(scores)[::-1][: body.top_k]
    results = [RerankResult(index=int(i), score=float(scores[i])) for i in indices]
    return RerankResponse(results=results)


# ── Metrics endpoint ──────────────────────────────────────────────


@app.get("/metrics")
async def metrics():
    """Expose OpenMetrics-formatted metrics for Prometheus scraping.

    Uses the same stdlib-based metrics collector from agent-svc (see
    ADR-0018 / ADR-0029) — no external metrics library required.
    """
    text = METRICS.generate_openmetrics()
    return Response(
        content=text,
        media_type="application/openmetrics-text; version=1.0.0",
    )


# ── Router includes ─────────────────────────────────────────────────
# Import routers at module bottom to avoid circular imports.
# All module-level symbols needed by routers are defined above.

from router_index import router_index
from router_migration import router_migration
from router_search import router_search

app.include_router(router_index, prefix="/index")
app.include_router(router_search, prefix="/search")
app.include_router(
    router_migration,
    prefix="/index/migrate",
    dependencies=[Depends(verify_api_key)],
)
