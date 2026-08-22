"""In-process fixture scenario routing for the grounded-answer eval harness.

Per the issue #570 review, per-case scenario routing is not feasible through
the HTTP ``/v2/answer`` boundary (scenario params are not forwarded and
``LLM_BASE_URL`` is process-wide). This module therefore drives the real
answer/research pipeline in-process: it constructs ``SearXNGClient`` (forcing
the case's search scenario) and ``LLMClient`` (scenario path/query) against the
deterministic fixture apps, exactly as the existing fixture contract tests do,
and injects them into ``run_answer`` / ``run_research``.

The scraper is served by a tiny harness-local stub app (``POST /scrape``) that
returns the case's pinned ``source_content`` for known fixture URLs, keeping the
harness deterministic and Docker-free. In the Compose lane the same pipeline can
run against the real ``scraper-svc`` by passing ``--scraper-url``.
"""

from __future__ import annotations

import contextlib
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

import httpx
from agent.llm import LLMClient
from agent.scraper_client import ScraperClient
from agent.searxng_client import SearXNGClient
from fastapi import FastAPI, Request

SEARCH_BASE_URL = "http://slopsearx-fixture"
LLM_BASE_URL = "http://llm-fixture"
SCRAPER_BASE_URL = "http://scraper-fixture"
FIXTURE_MODEL = "fixture-model"

# Endpoint-host allowlist preflight (no live egress). Hostnames only.
ALLOWED_EVAL_HOSTS = frozenset(
    {
        "test-site",
        "tier3-fixture",
        "slopsearx-fixture",
        "llm-svc",
        "llm-fixture",
        "scraper-svc",
        "scraper-fixture",
        "agent-svc-fixture",
        "localhost",
        "127.0.0.1",
        "::1",
    }
)

_MARKER = re.compile(r"\[(\d+)\]")


class EndpointAllowlistError(ValueError):
    """Raised when a routed endpoint host is not on the eval allowlist."""


def validate_endpoint_allowlist(urls: list[str]) -> None:
    """Fail fast when any *urls* host is outside ``ALLOWED_EVAL_HOSTS``."""
    for url in urls:
        if not url:
            continue
        host = (urlparse(url).hostname or "").lower()
        if host not in ALLOWED_EVAL_HOSTS:
            raise EndpointAllowlistError(
                f"endpoint host {host!r} is not allowlisted for eval egress"
            )


def create_scrape_stub(content_by_url: dict[str, str]) -> FastAPI:
    """A minimal in-process ``POST /scrape`` twin serving pinned content."""
    app = FastAPI(title="answer-eval scrape stub")

    @app.post("/scrape")
    async def scrape(request: Request) -> dict[str, Any]:
        body = await request.json()
        url = (body or {}).get("url", "")
        markdown = content_by_url.get(url)
        if markdown is None:
            return {
                "success": False,
                "error": f"no pinned content for {url}",
                "error_code": "SCRAPE_ERROR",
            }
        return {
            "success": True,
            "data": {"markdown": markdown, "source": "harness-stub"},
            "error": None,
        }

    return app


def _wire_client(client: Any, app: Any, base_url: str, timeout: float = 60.0) -> None:
    """Point an existing client's httpx transport at an in-process ASGI app."""
    client._client = httpx.AsyncClient(  # type: ignore[attr-defined]
        transport=httpx.ASGITransport(app=app),
        base_url=base_url,
        timeout=timeout,
    )


class _ScenarioSearXNGClient(SearXNGClient):
    """SearXNGClient that forces the case scenario on every search call.

    The answer/research loops invoke ``searxng.search(...)`` without a scenario
    argument; this subclass forwards the case scenario so the fixture ledger
    records it and the contradictory/zero-result paths behave deterministically.
    """

    def __init__(self, base_url: str, *, scenario: str, run_id: str, max_searches: int):
        super().__init__(base_url, max_searches=max_searches)
        self._force_scenario = scenario
        self._force_run_id = run_id

    async def search(  # type: ignore[override]
        self,
        query: str,
        limit: int = 10,
        categories: list[str] | None = None,
        sources: list[str] | None = None,
        *,
        raise_on_rate_limit: bool = False,
        scenario: str | None = None,
    ) -> tuple[list[dict], Any]:
        del scenario
        return await super().search(
            query,
            limit=limit,
            categories=categories,
            sources=sources,
            raise_on_rate_limit=raise_on_rate_limit,
            scenario=self._force_scenario,
        )


@dataclass
class FixtureRuntime:
    """The in-process fixture apps and wired clients for one case."""

    run_id: str
    search_app: Any
    llm_app: Any
    scraper_app: Any
    search_scenario: str
    llm_scenario: str
    scraper_url: str = SCRAPER_BASE_URL
    _created_clients: list[Any] = field(default_factory=list, repr=False)

    def search_client(self, *, max_searches: int = 5) -> SearXNGClient:
        client = _ScenarioSearXNGClient(
            SEARCH_BASE_URL,
            scenario=self.search_scenario,
            run_id=self.run_id,
            max_searches=max_searches,
        )
        _wire_client(client, self.search_app, SEARCH_BASE_URL)
        self._created_clients.append(client)
        return client

    def llm_client(self) -> LLMClient:
        client = LLMClient(
            base_url=f"{LLM_BASE_URL}/v1/scenarios/{self.llm_scenario}?run_id={self.run_id}",
            model=FIXTURE_MODEL,
        )
        _wire_client(client, self.llm_app, LLM_BASE_URL)
        self._created_clients.append(client)
        return client

    def scraper_client(self) -> ScraperClient:
        client = ScraperClient(self.scraper_url)
        if self.scraper_app is not None:
            _wire_client(client, self.scraper_app, self.scraper_url)
        self._created_clients.append(client)
        return client


def build_runtime(
    case: dict,
    run_id: str,
    *,
    scraper_url: str = SCRAPER_BASE_URL,
    use_scrape_stub: bool = True,
) -> FixtureRuntime:
    """Create a fresh FixtureRuntime for one case (isolated fixture state)."""
    from llm_svc.app import create_app as create_llm_app
    from slopsearx_fixture.app import create_app as create_search_app

    search_app = create_search_app()
    llm_app = create_llm_app()
    scraper_app = (
        create_scrape_stub(case.get("source_content") or {})
        if use_scrape_stub
        else None
    )
    validate_endpoint_allowlist(
        [scraper_url, *list((case.get("source_content") or {}).keys())]
    )
    return FixtureRuntime(
        run_id=run_id,
        search_app=search_app,
        llm_app=llm_app,
        scraper_app=scraper_app,
        search_scenario=case["search_fixture"]["scenario"],
        llm_scenario=case["llm_fixture"]["scenario"],
        scraper_url=scraper_url,
    )


def _parse_research_citations(answer: str, sources: list[dict]) -> list[dict]:
    citations: list[dict] = []
    seen: set[int] = set()
    for match in _MARKER.finditer(answer):
        index = int(match.group(1))
        if index not in seen and 1 <= index <= len(sources):
            seen.add(index)
            citations.append({"index": index, "url": sources[index - 1]["url"]})
    return citations


async def run_pipeline(case: dict, runtime: FixtureRuntime) -> dict:
    """Run the real answer/research pipeline and normalize the observed outcome."""
    from unittest import mock

    from agent.exceptions import ProviderOutputError, RetryableRateLimitError
    from agent.models import CitationStyle
    from agent.research.loop import run_answer, run_research

    target = case.get("target", "answer")
    query = case.get("query", "")
    num_sources = int(case.get("num_sources") or 5)
    retrieval_mode = case.get("retrieval_mode", "keyword")
    citation_style = (
        CitationStyle.compact
        if case.get("citation_style", "inline") == "compact"
        else CitationStyle.inline
    )

    search_client = runtime.search_client(max_searches=5)
    scraper_client = runtime.scraper_client()

    patches = [
        mock.patch(
            "agent.research.loop.SearXNGClient",
            side_effect=lambda *a, **k: search_client,
        ),
        mock.patch(
            "agent.research.loop.LLMClient",
            side_effect=lambda *a, **k: runtime.llm_client(),
        ),
        mock.patch(
            "agent.research.loop.ScraperClient",
            side_effect=lambda *a, **k: scraper_client,
        ),
    ]

    started = time.monotonic()
    previous_run_id = os.environ.get("TWIN_RUN_ID")
    os.environ["TWIN_RUN_ID"] = runtime.run_id
    try:
        with contextlib.ExitStack() as stack:
            for patch in patches:
                stack.enter_context(patch)
            try:
                if target == "research":
                    raw = await run_research(
                        prompt=query,
                        urls=None,
                        schema=None,
                        searxng_url=SEARCH_BASE_URL,
                        scraper_url=runtime.scraper_url,
                        llm_base_url=f"{LLM_BASE_URL}/v1/scenarios/{runtime.llm_scenario}",
                        llm_api_key="",
                        llm_model=FIXTURE_MODEL,
                        requested_model=None,
                        max_searches_per_request=5,
                        include_images=False,
                        citation_style=citation_style,
                        search_type="focused",
                    )
                    answer = raw.get("result", "")
                    sources = [
                        {"url": u, "title": "", "relevance": ""}
                        for u in raw.get("sources", [])
                    ]
                    return {
                        "protocol": {"status": 200, "success": True},
                        "answer": answer,
                        "sources": sources,
                        "citations": _parse_research_citations(answer, sources),
                        "latency_ms": int((time.monotonic() - started) * 1000),
                        "error": None,
                    }
                raw = await run_answer(
                    query=query,
                    num_sources=num_sources,
                    search_type="auto",
                    retrieval_mode=retrieval_mode,
                    searxng_url=SEARCH_BASE_URL,
                    scraper_url=runtime.scraper_url,
                    semantic_url="http://semantic-svc:8003",
                    llm_base_url=f"{LLM_BASE_URL}/v1/scenarios/{runtime.llm_scenario}",
                    llm_api_key="",
                    llm_model=FIXTURE_MODEL,
                    requested_model=None,
                    max_searches_per_request=5,
                    output_schema=None,
                    citation_style=citation_style,
                )
                return {
                    "protocol": {"status": 200, "success": True},
                    "answer": raw.get("answer", ""),
                    "sources": raw.get("sources", []),
                    "citations": raw.get("citations", []),
                    "latency_ms": raw.get(
                        "latency_ms", int((time.monotonic() - started) * 1000)
                    ),
                    "error": None,
                }
            except RetryableRateLimitError as exc:
                return {
                    "protocol": {"status": 429, "success": False},
                    "answer": "",
                    "sources": [],
                    "citations": [],
                    "latency_ms": int((time.monotonic() - started) * 1000),
                    "error": f"rate limited: {exc.detail}",
                }
            except ProviderOutputError as exc:
                return {
                    "protocol": {"status": 503, "success": False},
                    "answer": "",
                    "sources": [],
                    "citations": [],
                    "latency_ms": int((time.monotonic() - started) * 1000),
                    "error": str(exc.detail),
                }
            except Exception as exc:  # pragma: no cover - defensive
                return {
                    "protocol": {"status": None, "success": False},
                    "answer": "",
                    "sources": [],
                    "citations": [],
                    "latency_ms": int((time.monotonic() - started) * 1000),
                    "error": f"{type(exc).__name__}: {exc}",
                }
    finally:
        if previous_run_id is None:
            os.environ.pop("TWIN_RUN_ID", None)
        else:
            os.environ["TWIN_RUN_ID"] = previous_run_id
        for client in runtime._created_clients:
            with contextlib.suppress(Exception):
                await client.close()


async def fetch_search_ledger(runtime: FixtureRuntime) -> dict:
    """Return the search fixture ledger filtered to this run."""
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=runtime.search_app),
        base_url=SEARCH_BASE_URL,
    ) as client:
        response = await client.get("/ledger", params={"run_id": runtime.run_id})
        return response.json()


async def fetch_llm_diagnostics(runtime: FixtureRuntime) -> dict:
    """Return the LLM fixture diagnostics filtered to this run."""
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=runtime.llm_app),
        base_url=LLM_BASE_URL,
    ) as client:
        response = await client.get("/diagnostics", params={"run_id": runtime.run_id})
        return response.json()


async def scenario_usage(runtime: FixtureRuntime) -> dict:
    """Return the observed scenario usage from the fixture ledger/diagnostics."""
    ledger = await fetch_search_ledger(runtime)
    diagnostics = await fetch_llm_diagnostics(runtime)
    return {
        "search_scenario": runtime.search_scenario,
        "llm_scenario": runtime.llm_scenario,
        "search_observed_scenarios": sorted(
            {entry.get("scenario") for entry in ledger.get("entries", [])}
        ),
        "llm_observed_scenarios": sorted(
            {entry.get("scenario") for entry in diagnostics.get("entries", [])}
        ),
        "search_entry_count": len(ledger.get("entries", [])),
        "llm_entry_count": len(diagnostics.get("entries", [])),
    }
