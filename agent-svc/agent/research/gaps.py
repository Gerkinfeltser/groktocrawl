"""Gap detection for research coverage analysis."""

import json
import logging

from ..llm import LLMClient

logger = logging.getLogger(__name__)


async def _detect_gaps(combined_context: str, llm: LLMClient) -> list[str]:
    """Check if the research context has coverage gaps.

    Uses an LLM call to analyze the scraped context for gap signals:
    topics that are mentioned as missing, not covered, or insufficiently
    documented in the gathered sources.

    Returns a list of topic strings (max 5) for missing areas, or an
    empty list if coverage is adequate.
    """
    if not combined_context:
        return []

    gap_check_prompt = (
        "Analyze the following research context and identify specific topics "
        "that are mentioned as missing, not covered, or insufficiently "
        "documented. Return a JSON array of topic strings (max 5). "
        "Return [] if coverage is adequate.\n\n"
        f"Context:\n{combined_context[:4000]}"
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
