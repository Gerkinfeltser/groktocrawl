"""Research plan generation (Phase 0: Query Intelligence)."""

import json
import logging

from ..llm import LLMClient
from .prompts import QUERY_INTELLIGENCE_SYSTEM_PROMPT

logger = logging.getLogger(__name__)


async def _generate_research_plan(
    prompt: str,
    llm: LLMClient,
) -> dict:
    """Phase 0: Analyze the user prompt with an LLM and produce a research plan.

    Returns a dict with keys:
        reasoning (str): brief analysis of what the user needs
        research_strategy (str): "deep" or "focused"
        focused_queries (list[str]): 1-6 specific search queries

    On any failure (API error, timeout, invalid JSON, empty response),
    falls back to using the prompt itself as a single focused query.
    """
    try:
        raw_response = await llm.generate(
            system_prompt=QUERY_INTELLIGENCE_SYSTEM_PROMPT,
            user_prompt=prompt,
        )

        # Strip markdown code fences if present
        cleaned = raw_response.strip()
        cleaned = cleaned.removeprefix("```json")
        cleaned = cleaned.removeprefix("```")
        cleaned = cleaned.removesuffix("```")
        cleaned = cleaned.strip()

        if not cleaned:
            raise ValueError("Empty response from query intelligence LLM")

        plan = json.loads(cleaned)

        # Validate required fields
        queries = plan.get("focused_queries", [prompt])
        if not isinstance(queries, list) or len(queries) == 0:
            queries = [prompt]

        strategy = plan.get("research_strategy", "focused")
        if strategy not in ("deep", "focused"):
            strategy = "deep" if len(queries) > 1 else "focused"

        return {
            "reasoning": plan.get("reasoning", ""),
            "research_strategy": strategy,
            "focused_queries": queries,
        }
    except Exception as e:
        logger.warning(
            "Query intelligence LLM call failed, falling back to verbatim prompt: %s",
            e,
        )
        return {
            "reasoning": "Query intelligence unavailable — using prompt verbatim",
            "research_strategy": "focused",
            "focused_queries": [prompt],
        }
