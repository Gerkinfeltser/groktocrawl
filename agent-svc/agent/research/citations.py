"""Citation style helpers for the answer pipeline."""

import logging
import re
from typing import Any

from ..models import CitationStyle

logger = logging.getLogger(__name__)


def _build_answer_user_prompt(query: str, citation_style: Any) -> str:
    """Build the user prompt for the answer pipeline, adjusting citation
    instructions based on the requested citation style."""
    if citation_style == CitationStyle.compact:
        cite_instr = "Cite sources using [1](url), [2](url), etc. — include the URL directly in the citation marker."
    else:
        cite_instr = "Cite sources using [1], [2], etc. corresponding to the source numbers above."

    return (
        f"Answer the following question using ONLY the sources provided above.\n\n"
        f"Question: {query}\n\n"
        f"{cite_instr}"
    )


def _apply_citation_style(
    answer: str,
    source_map: list[dict[str, str]],
    citation_style: Any,
) -> tuple[str, list[dict]]:
    """Apply citation style post-processing to the LLM's answer text.

    Returns (modified_answer, citations_list).
    """
    citations: list[dict] = []
    seen_indices: set[int] = set()

    if citation_style == CitationStyle.compact:
        # Replace [N] with [N](url) — self-contained link
        # Use (?!\() to avoid matching already-linked [N](url) markers
        def _compact_replacer(match: re.Match) -> str:
            idx = int(match.group(1))
            if 1 <= idx <= len(source_map):
                seen_indices.add(idx)
                url = source_map[idx - 1]["url"]
                return f"[{idx}]({url})"
            return match.group(0)

        answer = re.sub(r"\[(\d+)\](?!\()", _compact_replacer, answer)
        for idx in sorted(seen_indices):
            citations.append({"index": idx, "url": source_map[idx - 1]["url"]})

    else:  # inline
        for match in re.finditer(r"\[(\d+)\]", answer):
            idx = int(match.group(1))
            if idx not in seen_indices and 1 <= idx <= len(source_map):
                seen_indices.add(idx)
                citations.append({"index": idx, "url": source_map[idx - 1]["url"]})

    return answer, citations
