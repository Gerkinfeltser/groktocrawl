"""OpenAI-compatible LLM client.

Works with any OpenAI-compatible API: OpenAI, Anthropic, OpenRouter,
Ollama, llama.cpp, vLLM, etc.
"""

import json
import logging

import httpx

logger = logging.getLogger(__name__)


class LLMClient:
    """Client for any OpenAI-compatible LLM API."""

    def __init__(
        self,
        base_url: str = "https://api.openai.com/v1",
        api_key: str = "",
        model: str = "gpt-4o-mini",
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self._client = httpx.AsyncClient(timeout=120)

    async def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        context: str | None = None,
        schema: dict | None = None,
    ) -> str:
        """Generate a response from the LLM.

        Args:
            system_prompt: System-level instructions.
            user_prompt: The user's task/question.
            context: Optional scraped context to include.
            schema: Optional JSON Schema for structured output.

        Returns:
            The LLM's response text.
        """
        messages = [{"role": "system", "content": system_prompt}]

        if context:
            messages.append({
                "role": "user",
                "content": f"Here is the information I gathered:\n\n{context}\n\nBased on this, {user_prompt}",
            })
        else:
            messages.append({"role": "user", "content": user_prompt})

        body: dict = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.3,
            "max_tokens": 8192,
        }

        # If schema is provided, request structured JSON output
        if schema:
            body["response_format"] = {"type": "json_object"}
            # Inject schema into the system prompt
            messages[0]["content"] += (
                f"\n\nYou MUST respond with valid JSON matching this schema:\n"
                f"{json.dumps(schema, indent=2)}"
            )

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

        try:
            resp = await self._client.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=body,
            )
            if resp.status_code != 200:
                logger.error("LLM API error %d: %s", resp.status_code, resp.text[:500])
                return f"Error: LLM API returned {resp.status_code}"

            result = resp.json()
            content = result["choices"][0]["message"]["content"]
            return content

        except Exception as e:
            logger.error("LLM call failed: %s", e)
            return f"Error: LLM call failed: {e}"

    async def close(self):
        await self._client.aclose()
