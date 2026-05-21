"""FastAPI application entrypoint for GroktoCrawl."""

import os

from fastapi import FastAPI
from redis import Redis
from rq import Queue

from .api import router
from .llm import LLMClient
from .scraper_client import ScraperClient
from .searxng_client import SearXNGClient
from .store import JobStore


def create_app() -> FastAPI:
    app = FastAPI(title="GroktoCrawl", version="0.1.0")

    redis_url = os.getenv("VALKEY_URL", "redis://valkey:6379/0")
    searxng_url = os.getenv("SEARXNG_URL", "http://searxng:8080")
    scraper_url = os.getenv("SCRAPER_URL", "http://scraper-svc:8001")
    llm_base_url = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")
    llm_api_key = os.getenv("LLM_API_KEY", "")
    llm_model = os.getenv("LLM_MODEL", "gpt-4o-mini")

    redis = Redis.from_url(redis_url, decode_responses=True)
    app.state.redis = redis
    app.state.job_store = JobStore(redis_url)
    app.state.rq_queue = Queue("groktocrawl", connection=redis)
    app.state.scraper_client = ScraperClient(scraper_url)
    app.state.searxng_client = SearXNGClient(searxng_url)
    app.state.llm_client = LLMClient(llm_base_url, llm_api_key, llm_model)
    app.state.searxng_url = searxng_url
    app.state.scraper_url = scraper_url
    app.state.llm_base_url = llm_base_url
    app.state.llm_api_key = llm_api_key
    app.state.llm_model = llm_model

    app.include_router(router)

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.on_event("shutdown")
    async def shutdown_event():
        await app.state.scraper_client.close()
        await app.state.searxng_client.close()
        await app.state.llm_client.close()

    return app


app = create_app()
