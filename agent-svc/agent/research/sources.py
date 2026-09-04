"""Request-scoped source artifacts shared by ranking and synthesis.

A ``SourceArtifact`` carries a URL plus the retrieval metadata and, when
available, the scraped Markdown so that ranking and final synthesis can
reuse one fetch instead of re-scraping the same URL. The projection kept in
``research.state.CompactSource`` deliberately excludes ``markdown``; this
artifact is never persisted into the replayable event state.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from common.url import extract_domain

# Documents are truncated to this many characters of Markdown when they are
# turned into LLM context blocks, mirroring the historical per-source limit.
DOCUMENT_MAX_CHARS = 8000


@dataclass
class SourceArtifact:
    """One scraped (or reused) source and its optional Markdown content."""

    url: str
    title: str = ""
    relevance: str = ""
    markdown: str | None = None
    source: str = "unknown"
    char_count: int = 0
    cache_state: str | None = None  # None / "live" / "from_cache"
    fetched_at: float | None = None
    # Hybrid-retrieval provenance (ADR-0052). ``retrieval`` records which
    # discovery source(s) produced the URL; ``score`` carries the vector
    # similarity score when one exists; ``cache_age_ms`` is set only when
    # content was reused from the Valkey scrape cache.
    retrieval: str = "web"  # "web" / "vector" / "both"
    score: float | None = None
    cache_age_ms: int | None = None
    # Request options are retained so a later stage can only reuse content
    # when it was fetched with an equivalent extraction contract.
    fetch_options: dict[str, Any] | None = None
    contents_options: dict[str, Any] | None = None
    extras: dict[str, Any] | None = None

    def to_document(self, max_chars: int = DOCUMENT_MAX_CHARS) -> str:
        """Render the source into a ``Source: url (domain: ...)`` context block."""
        domain = extract_domain(self.url)
        markdown = self.markdown or ""
        return f"Source: {self.url} (domain: {domain})\n\n{markdown[:max_chars]}"

    def to_source_detail(self) -> dict:
        """Project the artifact into the historical ``source_details`` dict shape."""
        return {
            "url": self.url,
            "source": self.source,
            "char_count": self.char_count,
        }

    def compatible_with(
        self,
        *,
        fetch_options: dict[str, Any] | None = None,
        contents_options: dict[str, Any] | None = None,
    ) -> bool:
        """Return whether this artifact satisfies another scrape contract."""
        return _options_fingerprint(self.fetch_options, self.contents_options) == (
            _options_fingerprint(fetch_options, contents_options)
        )


def _options_fingerprint(
    fetch_options: dict[str, Any] | None,
    contents_options: dict[str, Any] | None,
) -> str:
    """Build a stable, JSON-safe fingerprint for request-scoped reuse."""
    return json.dumps(
        {"fetch": fetch_options or {}, "contents": contents_options or {}},
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def artifacts_to_documents_and_details(
    artifacts: list[SourceArtifact],
) -> tuple[list[str], list[dict]]:
    """Split artifacts into the legacy ``(documents, source_details)`` pair."""
    return (
        [artifact.to_document() for artifact in artifacts],
        [artifact.to_source_detail() for artifact in artifacts],
    )
