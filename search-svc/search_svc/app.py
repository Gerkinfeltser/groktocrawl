"""Deterministic search fixture service for local integration tests.

Supports both GET (SearXNG JSON API compatible) and POST.
"""

from fastapi import FastAPI, Query
from pydantic import BaseModel

app = FastAPI(title="GroktoCrawl Search Fixture", version="0.1.0")


class SearchRequest(BaseModel):
    q: str
    limit: int = 5


DATASET = [
    {
        "url": "http://test-site:8000/llms.txt",
        "title": "Fixture llms.txt",
        "description": "Site publishes llms.txt.",
        "keywords": ["llms", "pricing", "agent"],
    },
    {
        "url": "http://test-site:8000/pricing",
        "title": "Fixture Pricing",
        "description": "Markdown negotiation page.",
        "keywords": ["pricing", "markdown", "accept"],
    },
    {
        "url": "http://test-site:8000/dynamic",
        "title": "Fixture Dynamic",
        "description": "JS-rendered page.",
        "keywords": ["dynamic", "browser", "js"],
    },
    {
        "url": "http://test-site:8000/",
        "title": "Fixture Home",
        "description": "Crawlable homepage.",
        "keywords": ["crawl", "map", "site"],
    },
]


def _search(q: str, limit: int = 5):
    q = q.lower()
    ranked = []
    for item in DATASET:
        score = sum(1 for kw in item["keywords"] if kw in q)
        ranked.append((score, item))
    ranked.sort(key=lambda x: x[0], reverse=True)
    results = []
    for score, item in ranked:
        if score > 0 or not results:
            results.append({
                "url": item["url"],
                "title": item["title"],
                "description": item["description"],
            })
        if len(results) >= limit:
            break
    return {"results": results}


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/search")
async def search_get(q: str = Query(""), limit: int = Query(5)):
    return _search(q, limit)


@app.post("/search")
async def search_post(req: SearchRequest):
    return _search(req.q, req.limit)
