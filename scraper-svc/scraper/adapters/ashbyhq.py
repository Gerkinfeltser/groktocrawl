"""
AshbyHQ ATS adapter — extracts job postings from AshbyHQ-powered career pages.

AshbyHQ embeds all job data as ``window.__appData`` JSON in the server-side
rendered HTML. No API calls are needed.

Fallback chain:
  1. ``window.__appData`` JSON extraction from SSR HTML
  2. Page scrape via readability-lxml
  3. ``AdapterError`` — falls through to the generic scrape pipeline
"""

from __future__ import annotations

import json
import logging
import re

import httpx

from ._helpers import scrape_page
from .base import AdapterContext, AdapterError, AdapterResult, SiteAdapter, adapter

logger = logging.getLogger(__name__)

# ── URL pattern matching ─────────────────────────────────────────

_ASHBYHQ_URL_PATTERNS = [
    # jobs.ashbyhq.com/{company}  (listing page)
    re.compile(
        r"^https?://jobs\.ashbyhq\.com/"
        r"(?P<company>[^/]+)/?$"
    ),
    # jobs.ashbyhq.com/{company}/{uuid}  (individual job)
    re.compile(
        r"^https?://jobs\.ashbyhq\.com/"
        r"(?P<company>[^/]+)/(?P<uuid>[a-f0-9\-]+)"
    ),
]


def _extract_company(url: str) -> str | None:
    """Extract the company slug from an AshbyHQ careers URL."""
    for pattern in _ASHBYHQ_URL_PATTERNS:
        m = pattern.search(url)
        if m:
            return m.group("company")
    return None


def _extract_uuid(url: str) -> str | None:
    """Extract the job UUID from an AshbyHQ job URL.

    Returns ``None`` for listing pages (no UUID).
    """
    m = _ASHBYHQ_URL_PATTERNS[1].search(url)
    if m:
        return m.group("uuid")
    return None


# ── Data extraction ──────────────────────────────────────────────


async def _fetch_html(url: str) -> str | None:
    """Fetch HTML content from an AshbyHQ URL.

    Uses a browser-like User-Agent to ensure SSR content is returned.
    """
    try:
        async with httpx.AsyncClient(
            timeout=15,
            follow_redirects=True,
        ) as client:
            resp = await client.get(
                url,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (compatible; GroktoCrawl/0.7.0; AshbyHQ adapter)"
                    ),
                },
            )
            if resp.status_code == 200:
                return resp.text
            logger.debug(
                "AshbyHQ fetch returned %d for %s", resp.status_code, url
            )
            return None
    except httpx.TimeoutException:
        logger.debug("AshbyHQ fetch timed out for %s", url)
        return None
    except httpx.RequestError as exc:
        logger.debug("AshbyHQ fetch failed for %s: %s", url, exc)
        return None


def _extract_appdata_json(html: str) -> dict | None:
    """Extract ``window.__appData`` JSON from AshbyHQ SSR HTML.

    Uses ``json.JSONDecoder.raw_decode`` for robust handling of nested JSON.
    """
    marker = "window.__appData"
    idx = html.find(marker)
    if idx == -1:
        return None

    # Find the opening brace after the marker
    start = html.find("{", idx)
    if start == -1:
        return None

    try:
        decoder = json.JSONDecoder()
        obj, _end = decoder.raw_decode(html, start)
        return obj
    except json.JSONDecodeError:
        logger.debug("Failed to parse __appData JSON (raw_decode)")
        return None


async def _fetch_and_parse_appdata(url: str) -> dict | None:
    """Fetch an AshbyHQ URL and extract ``window.__appData`` JSON.

    Returns the parsed JSON dict, or ``None`` on failure.
    """
    html = await _fetch_html(url)
    if not html:
        return None
    return _extract_appdata_json(html)


# ── HTML → markdown conversion ───────────────────────────────────


def _html_to_markdown(html: str) -> str:
    """Convert HTML job description to clean markdown.

    Uses readability-lxml + markdownify (standard deps of scraper-svc).
    Falls back to BeautifulSoup text extraction.
    """
    try:
        from markdownify import markdownify as md
        from readability import Document

        doc = Document(html)
        summary = doc.summary()
        markdown = md(summary, heading_style="ATX", strip=["script", "style"])
        markdown = re.sub(r"\n{3,}", "\n\n", markdown)
        return markdown.strip()
    except ImportError:
        pass
    except Exception as exc:
        logger.debug("readability-lxml failed: %s", exc)

    # Fallback: BeautifulSoup text extraction
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        text = soup.get_text(separator="\n", strip=True)
        return text[:20000]
    except Exception as exc:
        logger.debug("BeautifulSoup fallback failed: %s", exc)

    return html[:10000]


# ── Response formatting ──────────────────────────────────────────


def _format_listing(postings: list, company: str) -> tuple[str, dict]:
    """Convert a list of AshbyHQ job postings to a markdown table + metadata.

    Returns ``(markdown, metadata)``.
    """
    parts: list[str] = []
    parts.append(f"# {company} — Job Openings")
    parts.append("")

    if not postings:
        parts.extend(["*No job postings available at this time.*"])
        return "\n".join(parts), {
            "source": "ashbyhq-listing",
            "company": company,
            "total_openings": 0,
        }

    headers = [
        "Title",
        "Department",
        "Location",
        "Workplace Type",
        "Employment Type",
        "Posted",
    ]
    parts.append("| " + " | ".join(headers) + " |")
    parts.append("| " + " | ".join(["---"] * len(headers)) + " |")

    for p in postings:
        row = [
            p.get("title", ""),
            p.get("departmentName", "") or "",
            p.get("locationName", "") or "",
            p.get("workplaceType", "") or "",
            p.get("employmentType", "") or "",
            (p.get("publishedDate") or "")[:10],
        ]
        parts.append("| " + " | ".join(row) + " |")

    metadata: dict = {
        "source": "ashbyhq-listing",
        "company": company,
        "total_openings": len(postings),
    }

    return "\n".join(parts), metadata


def _format_job(data: dict, company: str, uuid: str) -> tuple[str, dict]:
    """Convert an AshbyHQ job posting response to markdown + metadata.

    Returns ``(markdown, metadata)``.
    """
    posting = data.get("posting", {})
    if not posting:
        raise AdapterError(
            f"No posting data found in AshbyHQ response for {company}/{uuid}"
        )

    title = posting.get("title", "")
    url = f"https://jobs.ashbyhq.com/{company}/{uuid}"

    # Build metadata
    metadata: dict = {
        "id": posting.get("id", ""),
        "title": title,
        "departmentName": posting.get("departmentName", ""),
        "teamName": posting.get("teamName", ""),
        "locationName": posting.get("locationName", ""),
        "workplaceType": posting.get("workplaceType", ""),
        "employmentType": posting.get("employmentType", ""),
        "publishedDate": (posting.get("publishedDate") or "")[:10],
        "updatedAt": (posting.get("updatedAt") or "")[:10],
        "jobRequisitionId": posting.get("jobRequisitionId", ""),
        "isRemote": posting.get("isRemote", False),
        "compensationTierSummary": posting.get("compensationTierSummary", ""),
        "shouldDisplayCompensation": posting.get(
            "shouldDisplayCompensation", False
        ),
        "source": "ashbyhq",
        "url": url,
    }

    # Build markdown
    parts: list[str] = []
    parts.append(f"# {title}")
    parts.append("")

    # Key details table
    detail_items: list[tuple[str, str]] = [
        ("Department", posting.get("departmentName", "")),
        ("Team", posting.get("teamName", "")),
        ("Location", posting.get("locationName", "")),
        ("Workplace Type", posting.get("workplaceType", "")),
        ("Employment Type", posting.get("employmentType", "")),
        ("Published", (posting.get("publishedDate") or "")[:10]),
        ("Updated", (posting.get("updatedAt") or "")[:10]),
        ("Job Requisition ID", posting.get("jobRequisitionId", "")),
        ("Remote", "Yes" if posting.get("isRemote") else "No"),
    ]

    # Add compensation if available
    compensation_summary = posting.get("compensationTierSummary", "")
    if compensation_summary:
        detail_items.append(("Compensation Summary", compensation_summary))

    parts.append("| Field | Value |")
    parts.append("|-------|-------|")
    for label, val in detail_items:
        if val:
            parts.append(f"| **{label}** | {val} |")
    parts.append("")

    # Description
    description_html = posting.get("descriptionHtml", "")
    if description_html:
        desc_md = _html_to_markdown(description_html)
        if desc_md:
            parts.append("## Description")
            parts.append("")
            parts.append(desc_md)
        else:
            parts.append("*No description available*")
    elif posting.get("descriptionPlainText"):
        parts.append("## Description")
        parts.append("")
        parts.append(posting["descriptionPlainText"])
    else:
        parts.append("*No description available*")

    parts.append("")
    parts.append(f"*Source: [AshbyHQ]({url})*")

    markdown = "\n".join(parts).strip()
    return markdown, metadata


# ── Adapter class ────────────────────────────────────────────────


@adapter
class AshbyHQAdapter(SiteAdapter):
    """Extract job postings from AshbyHQ-powered career pages."""

    name = "ashbyhq"

    patterns = _ASHBYHQ_URL_PATTERNS

    priority = 200

    async def scrape(self, url: str, ctx: AdapterContext) -> AdapterResult:
        company = _extract_company(url)
        if not company:
            raise AdapterError(
                f"Could not extract company from AshbyHQ URL: {url}"
            )

        uuid = _extract_uuid(url)

        # Tier 1: window.__appData JSON extraction from SSR HTML
        logger.info(
            "AshbyHQ adapter: trying __appData extraction for %s", url
        )
        data = await ctx.with_timeout(
            _fetch_and_parse_appdata(url), timeout=15
        )

        if data:
            if uuid:
                # Individual job page
                posting = data.get("posting")
                if not posting:
                    raise AdapterError(
                        "No posting data in AshbyHQ response "
                        f"for {company}/{uuid}"
                    )
                markdown, metadata = _format_job(data, company, uuid)
                logger.info(
                    "AshbyHQ adapter: extracted job %s (%d chars)",
                    uuid,
                    len(markdown),
                )
                return AdapterResult(
                    success=True,
                    markdown=markdown,
                    metadata=metadata,
                    source="ashbyhq",
                    url=url,
                )

            # Listing page
            postings = (
                data.get("jobBoard", {}).get("jobPostings", [])
            )
            if not postings:
                raise AdapterError(
                    f"No job postings found for AshbyHQ board: {company}"
                )
            markdown, metadata = _format_listing(postings, company)
            logger.info(
                "AshbyHQ adapter: extracted listing with %d jobs",
                len(postings),
            )
            return AdapterResult(
                success=True,
                markdown=markdown,
                metadata=metadata,
                source="ashbyhq-listing",
                url=url,
            )

        # Tier 2: readability page scrape
        logger.info(
            "AshbyHQ adapter: trying readability fallback for %s", url
        )
        result = await scrape_page(url)
        if result:
            return AdapterResult(
                success=True,
                markdown=result,
                metadata={"source": "ashbyhq-readability"},
                url=url,
            )

        raise AdapterError(
            f"Could not extract content from AshbyHQ URL: {url}"
        )
