"""FastAPI application entrypoint for GroktoCrawl."""
import logging
import os

from fastapi import FastAPI, Request, Depends
from redis import Redis
from rq import Queue

from .api import router
from .llm import LLMClient
from .scraper_client import ScraperClient
from .searxng_client import SearXNGClient
from .store import JobStore
from .auth import verify_api_key, AUTH_ENABLED, SECURITY_WARNING_HEADER, SECURITY_WARNING_BODY

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    app = FastAPI(
        title="GroktoCrawl",
        version="0.5.0",
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
    llm_base_url = os.getenv("LLM_BASE_URL", "http://llm-svc:8011/v1")
    llm_api_key = os.getenv("LLM_API_KEY", "")
    llm_model = os.getenv("LLM_MODEL", "fixture-model")
    searxng_url = os.getenv("SEARXNG_URL", "http://searxng:8080")
    scraper_url = os.getenv("SCRAPER_URL", "http://scraper-svc:8001")

    app.state.redis = Redis.from_url(redis_url, decode_responses=True)
    app.state.job_store = JobStore(redis_url)
    app.state.searxng_client = SearXNGClient(searxng_url)
    app.state.scraper_client = ScraperClient(scraper_url)
    app.state.llm_client = LLMClient(llm_base_url, llm_api_key, llm_model)
    app.state.llm_base_url = llm_base_url
    app.state.llm_api_key = llm_api_key
    app.state.llm_model = llm_model
    app.state.searxng_url = searxng_url
    app.state.scraper_url = scraper_url

    # ── Auth configuration ─────────────────────────────────────────
    if not AUTH_ENABLED:
        logger.warning(
            "WARNING: No API_KEY configured — API is publicly accessible without authentication. "
            "Set API_KEY in .env to enable auth. "
            "See README.md (Security section) for instructions."
        )
    else:
        logger.info("API key authentication enabled.")

    # ── Auth warning: middleware + health body ──────────────────────
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

    # ── Health endpoint (always unauthenticated, defined before router) ─
    @app.get("/health")
    async def health():
        if not AUTH_ENABLED:
            return {
                "status": "ok",
                "security": {
                    "auth_enabled": False,
                    "warning": SECURITY_WARNING_BODY,
                    "docs": "https://github.com/groktopus/groktocrawl#security",
                },
            }
        return {"status": "ok"}

    # ── Include API router with auth dependency ─────────────────────
    app.include_router(router, dependencies=[Depends(verify_api_key)])

    @app.on_event("shutdown")
    async def shutdown_event():
        await app.state.scraper_client.close()
        await app.state.searxng_client.close()
        await app.state.llm_client.close()

    return app


app = create_app()
