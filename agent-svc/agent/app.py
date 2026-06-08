"""FastAPI application entrypoint for GroktoCrawl."""

import json
import logging
import os
import time
import uuid

from fastapi import FastAPI, Request, Response, Depends
from fastapi.responses import PlainTextResponse
from redis import Redis
from rq import Queue

from .api import router
from .llm import LLMClient
from .scraper_client import ScraperClient
from .searxng_client import SearXNGClient
from .store import JobStore
from .health import check_all
from .metrics import METRICS
from .auth import verify_api_key, AUTH_ENABLED, SECURITY_WARNING_HEADER, SECURITY_WARNING_BODY

logger = logging.getLogger(__name__)


class JSONFormatter(logging.Formatter):
    """Structured JSON log formatter.

    Produces one JSON object per line with fields:
    timestamp, level, logger, message, and optional extra fields.
    """

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        # Include any extra fields set via extra={}
        for key, value in getattr(record, "extra_fields", {}).items():
            log_entry[key] = value
        # Include exception info if present
        if record.exc_info and record.exc_info[0]:
            log_entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_entry, default=str)


def setup_logging() -> None:
    """Configure structured JSON logging for all services.

    Replaces the default log format with JSON lines. Sets the root logger
    to INFO by default, controllable via ``LOG_LEVEL`` env var.
    """
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    handler = logging.StreamHandler()
    handler.setFormatter(JSONFormatter())
    root = logging.getLogger()
    root.setLevel(log_level)
    # Remove default handlers and add structured handler
    for h in root.handlers[:]:
        root.removeHandler(h)
    root.addHandler(handler)
    # Quiet noisy third-party loggers
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def create_app() -> FastAPI:
    setup_logging()

    app = FastAPI(
        title="GroktoCrawl",
        version="0.6.0",
        description="Self-hosted, Firecrawl-compatible web scraping and AI research API. MIT licensed.",
        servers=[
            {"url": "http://localhost:8080", "description": "Local development"},
        ],
        contact={
            "name": "GroktoCrawl",
            "url": "https://github.com/groktopus/groktocrawl",
        },
        license_info={
            "name": "MIT",
            "url": "https://github.com/groktopus/groktocrawl/blob/main/LICENSE",
        },
    )

    redis_url = os.getenv("VALKEY_URL", "redis://valkey:6379/0")
    conn = Redis.from_url(redis_url, decode_responses=True)
    queue = Queue(connection=conn)
    store = JobStore(redis_url)
    scraper_client = ScraperClient(os.getenv("SCRAPER_URL", "http://scraper-svc:8001"))
    searxng_client = SearXNGClient(os.getenv("SEARXNG_URL", "http://searxng:8080"))
    llm_client = LLMClient(
        base_url=os.getenv("LLM_BASE_URL", "http://llm-svc:8011/v1"),
        api_key=os.getenv("LLM_API_KEY", ""),
        model=os.getenv("LLM_MODEL", "deepseek-v4-flash"),
    )

    # ── App state ───────────────────────────────────────────────
    app.state.redis = conn
    app.state.queue = queue
    app.state.job_store = store
    app.state.scraper_client = scraper_client
    app.state.searxng_client = searxng_client
    app.state.llm_client = llm_client
    app.state.valkey_url = redis_url
    app.state.scraper_url = os.getenv("SCRAPER_URL", "http://scraper-svc:8001")
    app.state.searxng_url = os.getenv("SEARXNG_URL", "http://searxng:8080")
    app.state.llm_base_url = os.getenv("LLM_BASE_URL", "http://llm-svc:8011/v1")
    app.state.llm_api_key = os.getenv("LLM_API_KEY", "")
    app.state.llm_model = os.getenv("LLM_MODEL", "deepseek-v4-flash")
    app.state.semantic_url = os.getenv("SEMANTIC_URL", "http://semantic-svc:8003")

    # ── Middleware: request_id ───────────────────────────────────
    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        """Attach a unique request_id to every request and log start/end.

        Skips request_id generation for /health and /metrics to avoid
        polluting logs from pollers.
        """
        # Skip instrumentation for health/metrics pollers
        if request.url.path in ("/health", "/metrics"):
            return await call_next(request)

        request_id = str(uuid.uuid4())[:8]
        request.state.request_id = request_id
        start_time = time.monotonic()

        logger.info(
            "Request started",
            extra={"extra_fields": {"request_id": request_id, "method": request.method, "path": request.url.path}},
        )

        response = await call_next(request)

        duration_ms = (time.monotonic() - start_time) * 1000
        # Record request latency metric
        METRICS.histogram(
            "http_request_duration_seconds", "HTTP request latency by path and method",
            ["method", "path"],
        ).observe({"method": request.method, "path": request.url.path}, duration_ms / 1000)

        logger.info(
            "Request completed",
            extra={
                "extra_fields": {
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": response.status_code,
                    "duration_ms": round(duration_ms, 1),
                }
            },
        )
        return response

    # ── Security warning middleware ──────────────────────────────
    @app.middleware("http")
    async def security_warning_middleware(request: Request, call_next):
        response = await call_next(request)
        if not AUTH_ENABLED:
            response.headers[SECURITY_WARNING_HEADER] = (
                "No API key configured. API is publicly accessible. "
                "Set API_KEY=your-key in .env to enable authentication. "
                "See https://github.com/groktopus/groktocrawl#security"
            )
        return response

    # ── Health endpoint (always unauthenticated) ─────────────────
    @app.get("/health")
    async def health():
        """Return aggregate health status with per-dependency probes.

        Response shape (backward-compatible):
            {"status": "ok", "checks": {"valkey": {...}, "searxng": {...}, ...}}

        The top-level ``status`` field matches the existing contract for
        simple liveness checks. The ``checks`` field contains per-dependency
        probe results with status, latency_ms, and detail.
        """
        result = await check_all(
            valkey_url=app.state.valkey_url,
            searxng_url=app.state.searxng_url,
            scraper_url=app.state.scraper_url,
            browser_url="http://browser-svc:8012",
        )
        # Record health check outcomes as metrics
        dh_gauge = METRICS.gauge("dependency_health", "Dependency health status (1=ok, 0=down/-1=degraded)", ["dependency"])
        for name, probe in result.get("checks", {}).items():
            status_val = 0.0
            if probe.get("status") == "ok":
                status_val = 1.0
            elif probe.get("status") == "degraded":
                status_val = -1.0
            dh_gauge.set({"dependency": name}, status_val)

        if not AUTH_ENABLED:
            result["security"] = {
                "auth_enabled": False,
                "warning": SECURITY_WARNING_BODY,
                "docs": "https://github.com/groktopus/groktocrawl#security",
            }

        return result

    # ── Metrics endpoint (always unauthenticated) ────────────────
    @app.get("/metrics")
    async def metrics():
        """OpenMetrics-format metrics endpoint for Prometheus scraping.

        Returns counters, histograms, and gauges collected during agent-svc
        operation. See ``metrics.py`` for the full metric set.
        """
        # Update queue depth gauge before exporting
        try:
            active_jobs = app.state.job_store.list_active_jobs(status="processing", limit=1000)
            METRICS.gauge("queue_depth", "Current number of processing jobs").set(value=float(len(active_jobs)))
        except Exception:
            METRICS.gauge("queue_depth", "Current number of processing jobs").set(value=-1.0)

        return PlainTextResponse(
            content=METRICS.generate_openmetrics(),
            media_type="application/openmetrics-text; version=1.0.0",
        )

    # ── Include API router with auth dependency ─────────────────
    app.include_router(router, dependencies=[Depends(verify_api_key)])

    @app.on_event("shutdown")
    async def shutdown_event():
        await app.state.scraper_client.close()
        await app.state.searxng_client.close()
        await app.state.llm_client.close()

    return app


app = create_app()
