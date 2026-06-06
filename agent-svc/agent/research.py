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
            search_results, _health = await searxng.search(prompt, limit=10)
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


async def _scrape_urls(
    urls: list[str],
    scraper: ScraperClient,
    min_sources: int = 3,
    max_attempts: int | None = None,
) -> tuple[list[str], list[dict]]:
    """Scrape URLs and return (documents, source_details).

    Tries URLs in order until ``min_sources`` are successfully scraped
    or the list is exhausted (whichever comes first).
    ``max_attempts`` sets an upper bound on how many URLs are tried
    (default: try all provided URLs).
    """
    documents: list[str] = []
    source_details: list[dict] = []
    max_attempts = max_attempts or len(urls)
    attempts = 0

    for url in urls:
        if len(documents) >= min_sources:
            break
        if attempts >= max_attempts:
            break

        attempts += 1
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


ANSWER_SYSTEM_PROMPT = """You are GroktoCrawl, a helpful Q&A agent. Your job is to answer
the user's question using ONLY the web search results provided below.

RULES:
- Base your answer ONLY on the context provided. Do not use your pre-training knowledge.
- Cite sources using inline markers like [1], [2], etc. Each marker corresponds to a source URL listed below.
- If the context doesn't contain enough information to answer fully, say so clearly.
- Be concise but thorough. Lead with the direct answer, then add supporting detail.
- Use clean markdown formatting.
- Do not fabricate information or invent sources."""


async def run_answer(
    query: str,
    num_sources: int = 5,
    search_type: str = "auto",
    searxng_url: str = "http://searxng:8080",
    scraper_url: str = "http://scraper-svc:8001",
    llm_base_url: str = "https://api.openai.com/v1",
    llm_api_key: str = "",
    llm_model: str = "gpt-4o-mini",
    requested_model: str | None = None,
) -> dict:
    """Run a grounded Q&A pipeline: search → scrape → LLM → citations.

    Returns a dict with keys: answer, sources (list of dicts), citations (list of dicts),
    search_type, latency_ms.
    """
    import time
    start = time.monotonic()

    searxng = SearXNGClient(searxng_url)
    scraper = ScraperClient(scraper_url)
    effective_model = requested_model if requested_model and requested_model != "default" else llm_model
    llm = LLMClient(llm_base_url, llm_api_key, effective_model)

    try:
        # Step 1: Search (fetch extra results to allow for scrape failures)
        logger.info("Answer: searching for: %s", query)
        search_results, _health = await searxng.search(query, limit=num_sources * 2)
        target_urls = [r["url"] for r in search_results if r.get("url")]

        # Step 2: Scrape (keep trying until we have num_sources or exhaust the pool)
        documents, source_details = await _scrape_urls(target_urls, scraper, min_sources=num_sources, max_attempts=num_sources * 2)

        # Step 3: Build context with source markers
        context_parts = []
        for i, (doc, detail) in enumerate(zip(documents, source_details), start=1):
            url = detail["url"]
            title = next((r.get("title", "") for r in search_results if r.get("url") == url), "")
            context_parts.append(f"[{i}] Source: {url}\nTitle: {title}\n\n{doc}")

        context = "\n\n---\n\n".join(context_parts) if context_parts else ""

        if not context:
            elapsed = int((time.monotonic() - start) * 1000)
            return {
                "answer": "I was unable to find or scrape any relevant web pages to answer your question.",
                "sources": [],
                "citations": [],
                "search_type": search_type,
                "latency_ms": elapsed,
            }

        # Step 4: Build source_map for citation resolution
        source_map: list[dict[str, str]] = []
        for r in search_results:
            if r.get("url") in [s["url"] for s in source_details]:
                source_map.append({
                    "url": r["url"],
                    "title": r.get("title", ""),
                    "relevance": r.get("description", ""),
                })

        # Step 5: Call LLM
        user_prompt = (
            f"Answer the following question using ONLY the sources provided above.\n\n"
            f"Question: {query}\n\n"
            f"Cite sources using [1], [2], etc. corresponding to the source numbers above."
        )
        answer = await llm.generate(
            system_prompt=ANSWER_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            context=context,
        )

        # Step 6: Parse citations [N] from the answer
        citations: list[dict] = []
        seen_indices: set[int] = set()
        import re
        for match in re.finditer(r'\[(\d+)\]', answer):
            idx = int(match.group(1))
            if idx not in seen_indices and 1 <= idx <= len(source_map):
                seen_indices.add(idx)
                citations.append({"index": idx, "url": source_map[idx - 1]["url"]})

        elapsed = int((time.monotonic() - start) * 1000)

        return {
            "answer": answer,
            "sources": source_map,
            "citations": citations,
            "search_type": search_type,
            "latency_ms": elapsed,
        }
    finally:
        await searxng.close()
        await scraper.close()
        await llm.close()


async def run_answer_stream(
    query: str,
    num_sources: int = 5,
    search_type: str = "auto",
    searxng_url: str = "http://searxng:8080",
    scraper_url: str = "http://scraper-svc:8001",
    llm_base_url: str = "https://api.openai.com/v1",
    llm_api_key: str = "",
    llm_model: str = "gpt-4o-mini",
    requested_model: str | None = None,
):
    """Streaming version of run_answer. Yields SSE-suitable dicts.

    Yields:
      {"type": "sources", "sources": [...]} — source list (sent once before tokens)
      {"type": "token", "content": "..."} — individual tokens from the LLM
      {"type": "done", "answer": "...", "citations": [...], "latency_ms": N} — final
      {"type": "error", "content": "..."} — error
    """
    import time
    start = time.monotonic()

    searxng = SearXNGClient(searxng_url)
    scraper = ScraperClient(scraper_url)
    effective_model = requested_model if requested_model and requested_model != "default" else llm_model
    llm = LLMClient(llm_base_url, llm_api_key, effective_model)

    try:
        # Step 1: Search (fetch extra results to allow for scrape failures)
        logger.info("Answer (stream): searching for: %s", query)
        search_results, _health = await searxng.search(query, limit=num_sources * 2)
        target_urls = [r["url"] for r in search_results if r.get("url")]

        # Step 2: Scrape (keep trying until we have num_sources or exhaust the pool)
        documents, source_details = await _scrape_urls(target_urls, scraper, min_sources=num_sources, max_attempts=num_sources * 2)

        # Step 3: Build context
        context_parts = []
        source_map: list[dict[str, str]] = []
        for i, (doc, detail) in enumerate(zip(documents, source_details), start=1):
            url = detail["url"]
            title = next((r.get("title", "") for r in search_results if r.get("url") == url), "")
            context_parts.append(f"[{i}] Source: {url}\nTitle: {title}\n\n{doc}")
            source_map.append({"url": url, "title": title, "relevance": next(
                (r.get("description", "") for r in search_results if r.get("url") == url), ""
            )})

        context = "\n\n---\n\n".join(context_parts) if context_parts else ""

        if not context:
            yield {"type": "sources", "sources": []}
            yield {"type": "done", "answer": "No relevant web pages found.", "citations": [], "latency_ms": int((time.monotonic() - start) * 1000)}
            return

        # Yield sources before streaming tokens
        yield {"type": "sources", "sources": source_map}

        # Step 4: Stream LLM response
        user_prompt = (
            f"Answer the following question using ONLY the sources provided above.\n\n"
            f"Question: {query}\n\n"
            f"Cite sources using [1], [2], etc. corresponding to the source numbers above."
        )
        full_answer = ""
        async for event in llm.generate_stream(
            system_prompt=ANSWER_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            context=context,
        ):
            if event["type"] == "token":
                full_answer += event["content"]
                yield {"type": "token", "content": event["content"]}
            elif event["type"] == "error":
                yield {"type": "error", "content": event["content"]}
                return
            elif event["type"] == "done":
                full_answer = event["full_content"]

        # Step 5: Parse citations
        import re
        citations: list[dict] = []
        seen_indices: set[int] = set()
        for match in re.finditer(r'\[(\d+)\]', full_answer):
            idx = int(match.group(1))
            if idx not in seen_indices and 1 <= idx <= len(source_map):
                seen_indices.add(idx)
                citations.append({"index": idx, "url": source_map[idx - 1]["url"]})

        elapsed = int((time.monotonic() - start) * 1000)
        yield {"type": "done", "answer": full_answer, "citations": citations, "latency_ms": elapsed}

    finally:
        await searxng.close()
        await scraper.close()
        await llm.close()
