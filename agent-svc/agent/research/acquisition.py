"""Request-scoped concurrent source acquisition for search stages.

The acquisition result is intentionally content-bearing and short-lived. It is
passed between ranking, rich synthesis, and contents extraction during one
request, while the replayable research state continues to store only compact
source metadata.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from common.url import normalize_url

from ..barrier_guard import is_barrier_flagged, log_refusal
from ..scraper_client import ScraperClient
from .sources import SourceArtifact

logger = logging.getLogger(__name__)


@dataclass
class AcquisitionResult:
    """Accepted artifacts plus refusal/failure metadata for this request."""

    artifacts: list[SourceArtifact] = field(default_factory=list)
    refusals: dict[str, dict[str, Any]] = field(default_factory=dict)
    failures: dict[str, str] = field(default_factory=dict)

    def by_url(self) -> dict[str, SourceArtifact]:
        return {normalize_url(a.url): a for a in self.artifacts}


def _scrape_kwargs(
    scrape_options: dict[str, Any] | None,
    contents_options: dict[str, Any] | None,
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {}
    if scrape_options:
        kwargs["scrape_options"] = scrape_options
    if contents_options:
        kwargs["contents"] = contents_options
    return kwargs


async def acquire_source_artifacts(
    results: list[dict[str, Any]],
    scraper: ScraperClient,
    *,
    existing: list[SourceArtifact] | None = None,
    max_concurrent: int = 5,
    timeout: float = 30.0,
    scrape_options: dict[str, Any] | None = None,
    contents_options: dict[str, Any] | None = None,
    refused_urls: set[str] | None = None,
    unavailable_urls: set[str] | None = None,
) -> AcquisitionResult:
    """Fetch distinct compatible URLs concurrently with a bounded fan-out.

    Existing artifacts are reused only when their extraction options match the
    requested contract. Barrier responses are recorded as refusals and never
    returned as content-bearing artifacts. Failed URLs are retained as metadata
    so later stages can use their search descriptions as a deterministic
    fallback without issuing a second fetch.
    """
    result = AcquisitionResult()
    artifact_by_url = {
        normalize_url(a.url): a
        for a in (existing or [])
        if a.compatible_with(
            fetch_options=scrape_options, contents_options=contents_options
        )
        and a.markdown
    }
    seen: set[str] = set()
    candidates: list[tuple[str, dict[str, Any]]] = []
    for item in results:
        url = str(item.get("url") or "").strip()
        if not url:
            continue
        key = normalize_url(url)
        if key in seen:
            continue
        seen.add(key)
        if key in (refused_urls or set()):
            result.refusals[key] = {"error": "barrier refused by prior stage"}
            continue
        if key in (unavailable_urls or set()):
            result.failures[key] = "unavailable in prior stage"
            continue
        if key in artifact_by_url:
            continue
        candidates.append((key, item))

    semaphore = asyncio.Semaphore(max(1, max_concurrent))
    kwargs = _scrape_kwargs(scrape_options, contents_options)

    async def acquire_one(
        key: str, item: dict[str, Any]
    ) -> tuple[str, SourceArtifact | None, dict[str, Any] | None, str | None]:
        url = str(item["url"])
        async with semaphore:
            try:
                # Keep the no-options call shape compatible with lightweight
                # test doubles and older clients.
                if kwargs:
                    response = await asyncio.wait_for(
                        scraper.scrape(url, **kwargs), timeout=timeout
                    )
                else:
                    response = await asyncio.wait_for(
                        scraper.scrape(url), timeout=timeout
                    )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                return key, None, None, str(exc)

            if is_barrier_flagged(response):
                log_refusal(url, response)
                return key, None, response, None
            data = response.get("data") or {}
            markdown = data.get("markdown")
            if (
                not response.get("success")
                or not isinstance(markdown, str)
                or not markdown.strip()
            ):
                return key, None, None, str(response.get("error") or "empty scrape")
            return (
                key,
                SourceArtifact(
                    url=url,
                    title=str(item.get("title") or ""),
                    relevance=str(item.get("description") or ""),
                    markdown=markdown,
                    source=str(data.get("source") or "unknown"),
                    char_count=len(markdown),
                    cache_state="live",
                    fetch_options=scrape_options,
                    contents_options=contents_options,
                    extras=data.get("extras"),
                ),
                None,
                None,
            )

    acquired = await asyncio.gather(
        *(acquire_one(key, item) for key, item in candidates),
        return_exceptions=True,
    )
    for item in acquired:
        if isinstance(item, BaseException):
            logger.warning("Source acquisition task failed: %s", item)
            continue
        key, artifact, refusal, failure = item
        if artifact is not None:
            artifact_by_url[key] = artifact
        elif refusal is not None:
            result.refusals[key] = refusal
        elif failure is not None:
            result.failures[key] = failure

    # Preserve caller rank order and collapse canonical-equivalent duplicates.
    ordered: list[SourceArtifact] = []
    emitted: set[str] = set()
    for item in results:
        key = normalize_url(str(item.get("url") or ""))
        if key in emitted or key not in artifact_by_url:
            continue
        emitted.add(key)
        ordered.append(artifact_by_url[key])
    result.artifacts = ordered
    return result
