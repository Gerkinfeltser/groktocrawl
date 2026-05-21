"""FastAPI application for the scraper service.

Single endpoint: POST /scrape — takes a URL, returns clean markdown.
"""

import logging

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, HttpUrl

from .fetch import smart_scrape

logger = logging.getLogger(__name__)

app = FastAPI(title="GroktoCrawl Scraper", version="0.1.0")


class ScrapeRequest(BaseModel):
    url: str


class ScrapeResponse(BaseModel):
    success: bool
    data: dict | None = None
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
        return ScrapeResponse(
            success=True,
            data={
                "markdown": result.get("markdown", ""),
                "source": result.get("source", "unknown"),
                "url": request.url,
            },
        )
    except Exception as e:
        logger.exception("Scrape failed for %s", request.url)
        return ScrapeResponse(success=False, error=str(e))
