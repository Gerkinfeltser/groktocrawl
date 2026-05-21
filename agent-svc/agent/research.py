"""The agent research loop: search → scrape → think → answer.

Also provides the extract endpoint: scrape given URLs → LLM → structured data.
"""

import json
import logging

from .llm import LLMClient
from .searxng_client import SearXNGClient
from .scraper_client import ScraperClient

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are GroktoCrawl, an autonomous web research agent.
Your job is to answer the user's question based on the web content you've gathered.

Rules:
- Answer based ONLY on the context provided below.
- If the context doesn't contain enough information to answer fully, say so.
- Cite your sources by mentioning the URL when you use information from a specific page.
- Be concise but thorough.
- Format your answer in clean markdown."""

EXTRACT_SYSTEM_PROMPT = """You are GroktoCrawl, a structured data extraction agent.
Your job is to extract the requested information from the provided web content.

Rules:
- Extract data based ONLY on the content provided below.
- If the content doesn't contain the requested information, return an empty result.
- If a schema is provided, respond with valid JSON matching that schema exactly.
- Format your answer in clean markdown if no schema is provided."""


async def run_research(
    prompt: str,
    urls: list[str] | None = None,
    schema: dict | None = None,
    searxng_url: str = "http://searxng:8080",
    scraper_url: str = "http://scraper-svc:8001",
    llm_base_url: str = "https://api.openai.com/v1",
    llm_api_key: str = "",
    llm_model: str = "gpt-4o-mini",
) -> dict:
    """Execute the research loop: search → scrape → think → answer."""
    searxng = SearXNGClient(searxng_url)
    scraper = ScraperClient(scraper_url)
    llm = LLMClient(llm_base_url, llm_api_key, llm_model)

    try:
        target_urls = list(urls) if urls else []
        if not target_urls:
            logger.info("No URLs provided. Searching for: %s", prompt)
            search_results = await searxng.search(prompt, limit=10)
            target_urls = [r["url"] for r in search_results if r.get("url")]

        documents, source_details = await _scrape_urls(target_urls, scraper)
        context = "\n\n---\n\n".join(documents) if documents else ""

        if not context:
            return {"result": "I was unable to find or scrape any relevant web pages to answer your question.", "sources": [], "source_details": []}

        answer = await llm.generate(system_prompt=SYSTEM_PROMPT, user_prompt=prompt, context=context, schema=schema)
        _validate_json_if_schema(answer, schema)
        return {"result": answer, "sources": [s["url"] for s in source_details], "source_details": source_details}
    finally:
        await searxng.close()
        await scraper.close()
        await llm.close()


async def run_extract(
    urls: list[str],
    prompt: str | None = None,
    schema: dict | None = None,
    scraper_url: str = "http://scraper-svc:8001",
    llm_base_url: str = "https://api.openai.com/v1",
    llm_api_key: str = "",
    llm_model: str = "gpt-4o-mini",
) -> dict:
    """Extract structured data from given URLs. No search step."""
    scraper = ScraperClient(scraper_url)
    llm = LLMClient(llm_base_url, llm_api_key, llm_model)

    try:
        documents, source_details = await _scrape_urls(urls, scraper)
        context = "\n\n---\n\n".join(documents) if documents else ""

        if not context:
            return {"result": "No content could be extracted from the provided URLs.", "sources": [], "source_details": []}

        user_prompt = prompt or "Extract the requested information from the provided content."
        answer = await llm.generate(system_prompt=EXTRACT_SYSTEM_PROMPT, user_prompt=user_prompt, context=context, schema=schema)
        _validate_json_if_schema(answer, schema)
        return {"result": answer, "sources": [s["url"] for s in source_details], "source_details": source_details}
    finally:
        await scraper.close()
        await llm.close()


async def _scrape_urls(urls: list[str], scraper: ScraperClient) -> tuple[list[str], list[dict]]:
    """Scrape URLs and return (documents, source_details)."""
    documents = []
    source_details = []
    for url in urls[:5]:
        logger.info("Scraping: %s", url)
        result = await scraper.scrape(url)
        if result.get("success") and result.get("data", {}).get("markdown"):
            md = result["data"]["markdown"]
            documents.append(f"Source: {url}\n\n{md[:8000]}")
            source_details.append({"url": url, "source": result["data"].get("source", "unknown"), "char_count": len(md)})
        else:
            logger.warning("Failed to scrape %s: %s", url, result.get("error"))
    return documents, source_details


def _validate_json_if_schema(answer: str, schema: dict | None) -> None:
    """If a schema was provided, attempt to parse the answer as JSON."""
    if not schema:
        return
    try:
        cleaned = answer.strip()
        if cleaned.startswith("```json"):
            cleaned = cleaned[7:]
        if cleaned.startswith("```"):
            cleaned = cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        json.loads(cleaned)
    except (json.JSONDecodeError, Exception) as e:
        logger.warning("LLM response not valid JSON despite schema: %s", e)
