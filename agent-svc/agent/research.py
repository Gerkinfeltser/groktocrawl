"""The agent research loop: search → scrape → think → answer.

This is the core of the GroktoCrawl agent. Given a prompt, it:
1. Searches the web (if no seed URLs provided)
2. Scrapes the most relevant pages
3. Feeds everything to an LLM
4. Returns the synthesized answer
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
    """Execute the research loop.

    Returns:
        dict with keys: result (str), sources (list[str]), source_details (list[dict])
    """
    searxng = SearXNGClient(searxng_url)
    scraper = ScraperClient(scraper_url)
    llm = LLMClient(llm_base_url, llm_api_key, llm_model)

    try:
        # Step 1: Determine URLs to scrape
        target_urls = list(urls) if urls else []
        if not target_urls:
            logger.info("No URLs provided. Searching for: %s", prompt)
            search_results = await searxng.search(prompt, limit=10)
            target_urls = [r["url"] for r in search_results if r.get("url")]
            logger.info("Found %d candidate URLs", len(target_urls))

        # Step 2: Scrape the top URLs
        documents = []
        source_details = []

        # Limit to top 5 for MVP
        for url in target_urls[:5]:
            logger.info("Scraping: %s", url)
            result = await scraper.scrape(url)
            if result.get("success") and result.get("data", {}).get("markdown"):
                md = result["data"]["markdown"]
                doc = f"Source: {url}\n\n{md[:8000]}"  # Truncate per source
                documents.append(doc)
                source_details.append({
                    "url": url,
                    "source": result["data"].get("source", "unknown"),
                    "char_count": len(md),
                })
            else:
                logger.warning("Failed to scrape %s: %s", url, result.get("error"))

        # Step 3: Call the LLM with gathered context
        context = "\n\n---\n\n".join(documents) if documents else ""
        if not context:
            return {
                "result": "I was unable to find or scrape any relevant web pages to answer your question.",
                "sources": [],
                "source_details": [],
            }

        answer = await llm.generate(
            system_prompt=SYSTEM_PROMPT,
            user_prompt=prompt,
            context=context,
            schema=schema,
        )

        # If schema was requested, try to parse as JSON
        if schema:
            try:
                # Strip markdown code fences if present
                cleaned = answer.strip()
                if cleaned.startswith("```json"):
                    cleaned = cleaned[7:]
                if cleaned.startswith("```"):
                    cleaned = cleaned[3:]
                if cleaned.endswith("```"):
                    cleaned = cleaned[:-3]
                json.loads(cleaned)  # validate it's parseable
            except (json.JSONDecodeError, Exception) as e:
                logger.warning("LLM response not valid JSON despite schema: %s", e)

        return {
            "result": answer,
            "sources": [s["url"] for s in source_details],
            "source_details": source_details,
        }

    finally:
        await searxng.close()
        await scraper.close()
        await llm.close()
