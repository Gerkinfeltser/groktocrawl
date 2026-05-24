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
    system_text = "\n".join(m.content for m in req.messages if m.role == "system")

    if req.response_format and req.response_format.get("type") == "json_object":
        # Handle recovery prompts — extract iframe URLs from page content
        iframe_match = re.search(r'<iframe[^>]+src="([^"]+)"', user_text)
        if iframe_match and ("iframe_url" in system_text or "recovery" in system_text.lower()):
            content = json.dumps({
                "action": "iframe_url",
                "url": iframe_match.group(1),
            })
        elif "cloudflare" in system_text.lower() or "block_type" in system_text:
            content = json.dumps({
                "block_type": "js_challenge",
                "confidence": "medium",
                "page_indicators": ["challenge platform detected"],
                "alternative_paths": [],
                "human_action_required": False,
                "message": "Cloudflare JS challenge detected — could not bypass with available tools",
            })
        else:
            content = json.dumps({"result": "structured response"})
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
