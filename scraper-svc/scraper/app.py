"""FastAPI application for the scraper service.

Single endpoint: POST /scrape — takes a URL, returns clean markdown.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, HttpUrl

from .cookie_store import close_client, get_client
from .fetch import smart_scrape
from .meta import fetch_meta_tags

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app):
    """Connect to Valkey on startup, close on shutdown.

    Also loads site adapters (YouTube, etc.) — safe to call even
    if the adapters package is not yet installed.
    """
    from .adapters.base import get_registry

    try:
        registry = get_registry()
        registry.load_all()
        logger.info("Loaded %d site adapters", len(registry._entries))
    except Exception as exc:
        logger.warning("Failed to load adapters: %s", exc)

    await get_client()
    yield
    await close_client()


app = FastAPI(title="GroktoCrawl Scraper", version="0.1.0", lifespan=lifespan)


class ScrapeRequest(BaseModel):
    url: str


class DownloadData(BaseModel):
    """Binary content metadata for non-HTML responses."""
    filename: str
    content_type: str
    size: int
    data_url: str | None = None


class ScrapeResponse(BaseModel):
    success: bool
    data: dict | None = None
    error: str | None = None


class MetaResponse(BaseModel):
    success: bool = True
    title: str | None = None
    description: str | None = None
    og_description: str | None = None
    url: str | None = None
    error: str | None = None


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/scrape", response_model=ScrapeResponse)
async def scrape(request: ScrapeRequest):
    """Scrape a URL and return its content as clean markdown."""
    try:
        result = await smart_scrape(request.url)
        if result.get("error"):
            return ScrapeResponse(success=False, error=result["error"])
        data = {
            "markdown": result.get("markdown", ""),
            "source": result.get("source", "unknown"),
            "url": request.url,
            "quality": result.get("quality"),
        }
        if result.get("download"):
            data["download"] = result["download"]
        return ScrapeResponse(success=True, data=data)
    except Exception as e:
        logger.exception("Scrape failed for %s", request.url)
        return ScrapeResponse(success=False, error=str(e))


@app.post("/scrape/meta", response_model=MetaResponse)
async def scrape_meta(request: ScrapeRequest):
    """Extract meta tags from a URL using raw HTML (cheap, one GET).

    Returns <title>, <meta name="description">, and
    <meta property="og:description"> without full page rendering.
    """
    try:
        result = await fetch_meta_tags(request.url)
        return MetaResponse(
            success=True,
            title=result.get("title"),
            description=result.get("description"),
            og_description=result.get("og_description"),
            url=request.url,
        )
    except Exception as e:
        logger.exception("Meta fetch failed for %s", request.url)
        return MetaResponse(success=False, error=str(e))
