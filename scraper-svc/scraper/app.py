"""Scraper service: URL → markdown. Three-tier fetch strategy."""

from fastapi import FastAPI

app = FastAPI(title="GroktoCrawl Scraper", version="0.1.0")


@app.get("/health")
async def health():
    return {"status": "ok"}
