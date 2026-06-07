"""GroktoCrawl web portal — single-search-bar UI for human users."""

import json
import logging
import os

import httpx
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates

logger = logging.getLogger(__name__)

AGENT_BASE_URL = os.getenv("AGENT_BASE_URL", "http://agent-svc:8080")
ANSWER_URL = f"{AGENT_BASE_URL}/v2/answer"

templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "templates"))

app = FastAPI(
    title="GroktoCrawl Portal",
    version="0.1.0",
    description="Web portal for GroktoCrawl — self-hosted AI research.",
)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "portal-svc"}


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(request=request, name="index.html")


@app.post("/ask")
async def ask(query: str = Form(...), num_sources: int = Form(5)):
    """Proxy a grounded Q&A query to agent-svc, streaming SSE results back."""

    async def proxy_stream():
        async with httpx.AsyncClient(timeout=60) as client:
            async with client.stream(
                "POST",
                ANSWER_URL,
                json={
                    "query": query,
                    "num_sources": num_sources,
                    "stream": True,
                },
            ) as response:
                async for chunk in response.aiter_bytes():
                    yield chunk

    return StreamingResponse(proxy_stream(), media_type="text/event-stream")
