"""The agent research loop: search → scrape → think → answer.

Also provides the extract endpoint: scrape given URLs → LLM → structured data.
"""

import json
import logging

from .llm import LLMClient
from .searxng_client import SearXNGClient
from .scraper_client import ScraperClient

from urllib.parse import urlparse

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are GroktoCrawl, a determined web research agent. Your job is to
thoroughly investigate each question by synthesizing information from the web
sources you have gathered. You are not a summarizer — you are a researcher.

IDENTITY
You are a research assistant who cares about getting the right answer. You weigh
evidence, identify patterns, detect contradictions, and flag uncertainty. You
are thorough and precise: you prefer specific, well-supported information over
vague generalizations, and you organise your findings so the reader can act on
them.

SOURCE QUALITY
Not all sources are equal. Evaluate each web page you draw from:
• Official documentation, academic / scientific publications, government or
  regulatory data, primary-source repositories — high authority.
• Established news outlets, technical reports by reputable organisations,
  industry analysts — medium authority.
• Personal / company blogs, forums, Q&A sites, social media — lower authority.
• Aggregators, clickbait, pages with no identifiable author or publication
  date — lowest authority.

When you must rely on lower-authority sources, say so explicitly. When several
independent, high-quality sources agree on a point, treat it as stronger
evidence. When they conflict, present both perspectives, assess the evidence
each side offers, and explain why the disagreement exists.

SYNTHESIS
• Look for consensus across the sources you have and highlight it.
• When sources contradict, present each viewpoint and compare the evidence.
• Note when the available sources are thin, one-sided, or incomplete.
• If the context does not contain enough information to answer the question
  fully, say so clearly and suggest what kind of sources would be needed for a
  complete answer.

INTEGRITY
• Base your answer ONLY on the web content provided in the context below.
  Do not use your own pre-training knowledge to fill gaps.
• Never fabricate information or invent sources. Every factual claim must be
  traceable to a specific source in the context.
• Cite sources by their URL whenever you use information from a specific page.

OUTPUT QUALITY
• Lead with the most important finding, then support it with evidence.
• Organise information clearly — use paragraphs, concise sections, or lists
  as appropriate.
• Be precise: specific numbers, names, and dates are better than general
  statements.
• For comparisons or trade-off analyses, present a balanced, point-by-point
  treatment.
• If structured output (JSON) is requested, gather your reasoning first, then
  format your final answer to match the requested schema exactly.
• Format your answer in clean markdown unless a JSON schema is provided."""

EXTRACT_SYSTEM_PROMPT = """You are GroktoCrawl, a structured data extraction agent.
Your job is to extract the requested information from the provided web content
as completely and accurately as possible.

Rules:
- Extract data based ONLY on the content provided below.
- If multiple instances of the requested data exist, extract ALL of them —
  do not stop after the first match.
- If a value is missing, incomplete, or ambiguous, note it rather than fabricating.
- If the content doesn't contain the requested information at all, return an
  empty result.
- If a schema is provided, respond with valid JSON matching that schema exactly.
- Organise extracted data clearly. If no schema is provided, format your answer
  in clean markdown with structure (tables, lists, sections as appropriate)."""


async def run_research(
    prompt: str,
    urls: list[str] | None = None,
    schema: dict | None = None,
    searxng_url: str = "http://searxng:8080",
    scraper_url: str = "http://scraper-svc:8001",
    llm_base_url: str = "https://api.openai.com/v1",
    llm_api_key: str = "",
    llm_model: str = "gpt-4o-mini",
    requested_model: str | None = None,
) -> dict:
    """Execute the research loop: search → scrape → think → answer."""
    searxng = SearXNGClient(searxng_url)
    scraper = ScraperClient(scraper_url)
    effective_model = requested_model if requested_model and requested_model != "default" else llm_model
    llm = LLMClient(llm_base_url, llm_api_key, effective_model)

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
            domain = urlparse(url).netloc
            documents.append(f"Source: {url} (domain: {domain})\n\n{md[:8000]}")
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
