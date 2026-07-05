"""Citations route handler — resolve inline citation markers."""

import logging
import re

from fastapi import APIRouter, Request

from ..exceptions import RateLimitedError
from ..metrics import METRICS
from ..models import (
    CitationsResolveRequest,
    CitationsResolveResponse,
    CitationStyle,
    ResolvedCitation,
    Source,
)
from ._helpers import _get_client_ip

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/v2/citations/resolve", response_model=CitationsResolveResponse)
async def resolve_citations(request: Request, body: CitationsResolveRequest):
    """Resolve inline citation markers to full citations.

    Takes markdown text with ``[N]`` markers and a source list.  Returns
    the text with citations resolved according to the requested style.

    Citation styles:
        - ``inline``: Keep ``[N]`` markers as-is (returns original text).
        - ``compact``: Replace ``[N]`` with ``[N](url)`` self-contained links.
    """
    # ── Per-client rate limit check (VAL-CR-018) ────────────
    client_ip = _get_client_ip(request)
    rate_limiter = request.app.state.rate_limiter
    allowed, _rate_remaining = await rate_limiter.check(f"{client_ip}:search")
    if not allowed:
        METRICS.counter("search_calls_total", "Total search calls", ["status"]).inc(
            {"status": "rate_limited"}
        )
        raise RateLimitedError(
            detail=f"Per-client rate limit exceeded ({rate_limiter.limit}/{rate_limiter.window}s)"
        )

    resolved: list[ResolvedCitation] = []
    seen_indices: set[int] = set()
    text = body.text
    style = body.style

    # Build lookup: index (1-based) → source
    src_map: dict[int, Source] = {}
    for i, src in enumerate(body.sources, start=1):
        src_map[i] = src

    if style == CitationStyle.compact:
        # Replace [N] with [N](url) — self-contained link
        # Use (?!\() to avoid matching already-linked [N](url) markers
        def _compact_replacer(match: re.Match) -> str:
            idx = int(match.group(1))
            if idx in src_map and idx not in seen_indices:
                seen_indices.add(idx)
                src = src_map[idx]
                resolved.append(
                    ResolvedCitation(
                        index=idx,
                        url=src.url,
                        title=src.title,
                        marker_text=match.group(0),
                        resolved_text=f"[{idx}]({src.url})",
                    )
                )
                return f"[{idx}]({src.url})"
            return match.group(0)

        text = re.sub(r"\[(\d+)\](?!\()", _compact_replacer, text)
    else:  # inline — return as-is but build citation list
        for match in re.finditer(r"\[(\d+)\]", text):
            idx = int(match.group(1))
            if idx in src_map and idx not in seen_indices:
                seen_indices.add(idx)
                src = src_map[idx]
                resolved.append(
                    ResolvedCitation(
                        index=idx,
                        url=src.url,
                        title=src.title,
                        marker_text=match.group(0),
                        resolved_text=match.group(0),
                    )
                )

    return CitationsResolveResponse(
        resolved_text=text,
        citations=resolved,
        style=style,
        citation_count=len(resolved),
    )
