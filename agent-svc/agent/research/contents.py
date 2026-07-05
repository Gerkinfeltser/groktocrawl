"""Content extraction helpers: highlights, summary, and result processing."""

import asyncio
import logging

from .prompts import HIGHLIGHTS_SYSTEM_PROMPT, SUMMARY_SYSTEM_PROMPT

logger = logging.getLogger(__name__)


async def extract_highlights(
    text: str,
    query: str | None,
    max_chars: int,
    llm_client,
) -> str:
    """Extract the most relevant passages from text matching the query.

    Uses the LLM to identify and extract verbatim or near-verbatim passages
    that are most relevant to the query. Returns up to max_chars characters.

    Graceful degradation: returns empty string on LLM failure.

    Args:
        text: The scraped page content (markdown).
        query: Search query to match passages against (optional, defaults to "the main topic").
        max_chars: Maximum characters to return.
        llm_client: An LLMClient instance for generating responses.

    Returns:
        Extracted passages as a string, or empty string on failure.
    """
    if not text or not text.strip():
        return ""

    effective_query = query or "the main topic"
    truncated = text[:10000]

    try:
        user_prompt = (
            f"From the text below, extract the passages most relevant to: {effective_query}\n"
            f"Return up to {max_chars} characters. Return only the extracted passages, "
            f"no commentary."
        )
        result = await llm_client.generate(
            system_prompt=HIGHLIGHTS_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            context=truncated,
        )
        # Trim to requested max characters
        if len(result) > max_chars:
            result = result[:max_chars].rsplit(" ", 1)[0]
        return result.strip()
    except Exception as e:
        logger.warning("extract_highlights failed: %s", e)
        return ""


async def extract_summary(
    text: str,
    query: str | None,
    max_tokens: int,
    llm_client,
) -> str:
    """Generate a concise summary of the text.

    Uses the LLM to produce a brief summary, optionally focused on a query.

    Graceful degradation: returns empty string on LLM failure.

    Args:
        text: The scraped page content (markdown).
        query: Optional focus for the summary.
        max_tokens: Approximate token budget for the summary.
        llm_client: An LLMClient instance for generating responses.

    Returns:
        Summary text as a string, or empty string on failure.
    """
    if not text or not text.strip():
        return ""

    focus_clause = f" with focus on: {query}" if query else ""
    truncated = text[:10000]

    try:
        user_prompt = (
            f"Summarize the text below{focus_clause}.\n"
            f"Keep it to {max_tokens} tokens or fewer."
        )
        result = await llm_client.generate(
            system_prompt=SUMMARY_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            context=truncated,
        )
        return result.strip()
    except Exception as e:
        logger.warning("extract_summary failed: %s", e)
        return ""


async def process_contents_for_results(
    results: list[dict],
    query: str,
    contents_options,
    llm_client,
    scraper_client,
) -> list[dict]:
    """Apply contents options (highlights, summary, extras) to search results.

    Scrapes each result URL, then applies per-result LLM highlights and/or
    summaries based on the contents_options configuration. Handles extras
    extraction by passing contents to the scraper-svc.

    Graceful degradation: LLM failures return empty strings. Scraping failures
    skip the result.

    Args:
        results: List of search result dicts (each has url, title, description).
        query: The original search query.
        contents_options: ContentsOptions from the request.
        llm_client: An LLMClient instance.
        scraper_client: A ScraperClient instance.

    Returns:
        List of enriched result dicts with additional keys: highlights, summary,
        extras, markdown.
    """
    enriched: list[dict] = []

    highlights_opts: dict = {}
    summary_opts: dict = {}
    want_highlights = False
    want_summary = False

    if contents_options.highlights is not None:
        want_highlights = True
        if isinstance(contents_options.highlights, dict):
            highlights_opts = contents_options.highlights

    if contents_options.summary is not None:
        want_summary = True
        if isinstance(contents_options.summary, dict):
            summary_opts = contents_options.summary

    want_extras = contents_options.extras is not None

    # Build scraper request body — include contents for extras extraction
    scraper_body: dict = {"url": ""}
    if want_extras:
        scraper_body["contents"] = {
            "extras": contents_options.extras.model_dump(exclude_none=True)
        }

    semaphore = asyncio.Semaphore(2)

    async def _process_one(result: dict) -> dict:
        url = result.get("url", "")
        entry = dict(result)  # Copy
        if not url:
            return entry

        async with semaphore:
            # Scrape the URL
            try:
                scraper_body["url"] = url
                scraped = await asyncio.wait_for(
                    scraper_client._client.post(
                        f"{scraper_client.base_url}/scrape",
                        json=scraper_body,
                    ),
                    timeout=30,
                )
                scraped_data = scraped.json()
            except Exception as e:
                logger.warning("Failed to scrape %s for contents: %s", url, e)
                return entry

            if not scraped_data.get("success"):
                return entry

            data = scraped_data.get("data", {})
            markdown = data.get("markdown", "")

            if want_extras:
                entry["extras"] = data.get("extras")

            if not markdown:
                return entry

            entry["markdown"] = markdown

            # ── Highlights ──────────────────────────────────
            if want_highlights:
                hq = highlights_opts.get("query") or query
                hmax = highlights_opts.get("maxCharacters", 500)
                try:
                    entry["highlights"] = await extract_highlights(
                        markdown, hq, hmax, llm_client
                    )
                except Exception:
                    entry["highlights"] = ""

            # ── Summary ─────────────────────────────────────
            if want_summary:
                sq = summary_opts.get("query") or query
                smax = summary_opts.get("maxTokens", 150)
                try:
                    entry["summary"] = await extract_summary(
                        markdown, sq, smax, llm_client
                    )
                except Exception:
                    entry["summary"] = ""

        return entry

    tasks = [asyncio.create_task(_process_one(r)) for r in results]
    enriched = await asyncio.gather(*tasks)

    return list(enriched)
