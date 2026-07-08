"""Gap detection for research coverage analysis."""

import json
import logging

from ..llm import LLMClient

logger = logging.getLogger(__name__)


async def _detect_gaps(
    combined_context: str,
    llm: LLMClient,
    original_query: str = "",
) -> list[str]:
    """Check if the research context has coverage gaps.

    Uses an LLM call to analyze the scraped context for topic areas
    that are not adequately covered relative to the original research query.

    Returns a list of topic strings (max 5) for missing areas, or an
    empty list if coverage is adequate.
    """
    if not combined_context:
        return []

    query_context = f'Original research query: "{original_query}"\n\n' if original_query else ""
    gap_check_prompt = (
        f"{query_context}Analyze the following research context and identify specific topics, "
        "angles, or aspects of the original query that are NOT adequately covered "
        "by the gathered sources. Focus on what's missing or thin, not what's present. "
        "Return a JSON array of topic strings (max 5) that would make good follow-up search queries. "
        "Return [] if you're satisfied with coverage.\n\n"
        f"Context:\n{combined_context[:12000]}"
    )
    try:
        result = await llm.generate(
            system_prompt="You are a research gap analyzer.",
            user_prompt=gap_check_prompt,
        )
        cleaned = result.strip().removeprefix("```json").removesuffix("```").strip()
        gaps = json.loads(cleaned)
        if isinstance(gaps, list) and len(gaps) <= 5:
            return [g for g in gaps if isinstance(g, str)]
        return []
    except (json.JSONDecodeError, Exception) as e:
        logger.warning("Gap detection failed: %s", e)
        return []
