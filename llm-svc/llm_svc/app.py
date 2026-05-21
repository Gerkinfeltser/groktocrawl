"""Deterministic OpenAI-compatible chat completions fixture."""

import json
import re
from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="GroktoCrawl LLM Fixture", version="0.1.0")


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatCompletionRequest(BaseModel):
    model: str
    messages: list[ChatMessage]
    temperature: float | None = None
    max_tokens: int | None = None
    response_format: dict | None = None


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/v1/chat/completions")
async def chat_completions(req: ChatCompletionRequest):
    user_text = "\n".join(m.content for m in req.messages if m.role == "user")
    sources = re.findall(r"Source:\s*(\S+)", user_text)
    if req.response_format and req.response_format.get("type") == "json_object":
        content = json.dumps({"result": "structured response", "sources": sources})
    else:
        if sources:
            content = "Synthesized answer from provided context.\n\nSources used:\n" + "\n".join(f"- {s}" for s in sources)
        else:
            content = "Synthesized answer from provided context."
    return {
        "id": "chatcmpl-fixture",
        "object": "chat.completion",
        "created": 0,
        "model": req.model,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }
