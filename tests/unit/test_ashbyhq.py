"""Unit tests for the AshbyHQ adapter's API tiers.

Covers:
- URL pattern matching (jobs.ashbyhq.com and api.ashbyhq.com posting-api)
- Board-name derivation from the final URL path segment
- Format helpers (listing table, single job detail, compensation, location)
- Listing-vs-individual-job dispatch
- SSR fallback when the API tier fails (incl. unknown board → 404)
- Authenticated RPC tier gating (skipped without ASHBY_API_KEY, engaged with it)
- Registry registration + dispatch for jobs.ashbyhq.com URLs

No live HTTP is used; the fetch helpers are monkeypatched with inline samples.
"""

from __future__ import annotations

import importlib

import pytest
import scraper.adapters.ashbyhq as mod
import scraper.adapters.base as base_mod
from scraper.adapters.ashbyhq import (
    _ASHBYHQ_URL_PATTERNS,
    AshbyHQAdapter,
    _extract_board,
    _extract_uuid,
    _format_api_job,
    _format_api_listing,
    _format_compensation,
    _location_string,
)
from scraper.adapters.base import AdapterContext, AdapterError, AdapterRegistry

# ── Sample data (inline, no HTTP) ────────────────────────────────

JOB_1_UUID = "11111111-1111-1111-1111-111111111111"

SAMPLE_JOBS = [
    {
        "id": JOB_1_UUID,
        "title": "Software Engineer",
        "department": "Product",
        "team": "Engineering",
        "employmentType": "FullTime",
        "location": "North America",
        "secondaryLocations": ["Remote"],
        "isRemote": True,
        "isListed": True,
        "publishedAt": "2024-01-15T10:00:00.000+00:00",
        "jobUrl": f"https://jobs.ashbyhq.com/acme/{JOB_1_UUID}",
        "applyUrl": f"https://jobs.ashbyhq.com/acme/{JOB_1_UUID}/application",
        "descriptionHtml": "<p>Build great software.</p>",
        "descriptionPlain": "Build great software.",
        "compensation": {
            "compensationTierSummary": "USD $150,000 - $200,000",
            "compensationTiers": [{"title": "Engineering", "summary": "$150k-$200k"}],
            "summaryComponents": [],
        },
    },
    {
        "id": "22222222-2222-2222-2222-222222222222",
        "title": "Product Designer",
        "department": "Design",
        "team": "Design",
        "employmentType": "FullTime",
        "location": "Europe",
        "secondaryLocations": [],
        "isRemote": False,
        "isListed": True,
        "publishedAt": "2024-02-01T09:00:00.000+00:00",
        "jobUrl": "https://jobs.ashbyhq.com/acme/22222222-2222-2222-2222-222222222222",
        "descriptionHtml": "<p>Design great products.</p>",
        "compensation": {},
    },
]

SAMPLE_RPC_RESULTS = [
    {
        "id": JOB_1_UUID,
        "title": "Software Engineer",
        "departmentName": "Product",
        "teamName": "Engineering",
        "locationName": "North America",
        "employmentType": "FullTime",
        "isRemote": True,
        "isListed": True,
        "publishedDate": "2024-01-15T10:00:00.000+00:00",
        "compensationTierSummary": "USD $150,000 - $200,000",
    },
]

SSR_JOB_DATA = {
    "posting": {
        "id": JOB_1_UUID,
        "title": "Software Engineer",
        "departmentName": "Product",
        "locationName": "North America",
        "descriptionHtml": "<p>SSR description for the job.</p>",
    }
}

SSR_LISTING_DATA = {
    "jobBoard": {
        "jobPostings": [
            {
                "title": "SSR Job A",
                "departmentName": "Product",
                "locationName": "United States",
                "publishedDate": "2024-01-01T00:00:00",
            }
        ]
    }
}


# ── URL matching ─────────────────────────────────────────────────


def test_matches_jobs_listing_url():
    url = "https://jobs.ashbyhq.com/linear"
    assert any(p.search(url) for p in _ASHBYHQ_URL_PATTERNS)


def test_matches_jobs_individual_url():
    url = f"https://jobs.ashbyhq.com/linear/{JOB_1_UUID}"
    assert any(p.search(url) for p in _ASHBYHQ_URL_PATTERNS)


def test_matches_posting_api_url():
    url = "https://api.ashbyhq.com/posting-api/job-board/linear"
    assert any(p.search(url) for p in AshbyHQAdapter.patterns)


def test_does_not_match_non_ashby():
    url = "https://example.com/careers"
    assert not any(p.search(url) for p in AshbyHQAdapter.patterns)


# ── Board derivation ─────────────────────────────────────────────


def test_board_from_jobs_slug():
    assert _extract_board("https://jobs.ashbyhq.com/linear") == "linear"


def test_board_from_jobs_slug_with_uuid():
    url = f"https://jobs.ashbyhq.com/linear/{JOB_1_UUID}"
    assert _extract_board(url) == "linear"


def test_board_from_posting_api_url():
    url = "https://api.ashbyhq.com/posting-api/job-board/linear"
    assert _extract_board(url) == "linear"


def test_board_none_for_unrelated():
    assert _extract_board("https://example.com/careers") is None


def test_uuid_extraction():
    url = f"https://jobs.ashbyhq.com/linear/{JOB_1_UUID}"
    assert _extract_uuid(url) == JOB_1_UUID


def test_uuid_none_for_listing():
    assert _extract_uuid("https://jobs.ashbyhq.com/linear") is None


# ── Format helpers ───────────────────────────────────────────────


def test_listing_table_contains_title_location_department():
    markdown, metadata = _format_api_listing(SAMPLE_JOBS, "acme")
    assert "# acme — Job Openings" in markdown
    assert "Software Engineer" in markdown
    assert "North America, Remote" in markdown
    assert "Product" in markdown
    assert metadata["total_openings"] == 2
    assert metadata["source"] == "ashbyhq-api"


def test_individual_job_has_description_section():
    markdown, metadata = _format_api_job(SAMPLE_JOBS[0], "acme", JOB_1_UUID)
    assert "## Description" in markdown
    assert metadata["source"] == "ashbyhq-api"


def test_compensation_surfaced_in_listing():
    markdown, _ = _format_api_listing(SAMPLE_JOBS, "acme")
    assert "USD $150,000 - $200,000" in markdown


def test_compensation_surfaced_in_individual_job():
    markdown, metadata = _format_api_job(SAMPLE_JOBS[0], "acme", JOB_1_UUID)
    assert "USD $150,000 - $200,000" in markdown
    assert metadata.get("compensation") is not None


def test_compensation_formatter_empty():
    assert _format_compensation({}) == ""
    assert _format_compensation(None) == ""


def test_location_string_combines_secondary():
    assert _location_string(SAMPLE_JOBS[0]) == "North America, Remote"
    assert _location_string(SAMPLE_JOBS[1]) == "Europe"


def test_listing_empty():
    markdown, metadata = _format_api_listing([], "acme")
    assert metadata["total_openings"] == 0
    assert "Job Openings" in markdown


def test_api_listing_escapes_pipe_in_cell():
    # VAL-FU-003: a title containing a pipe must render as one cell, not
    # split the table into extra columns.
    job = {
        "id": JOB_1_UUID,
        "title": "Engineer | Senior",
        "department": "Product",
        "team": "Engineering",
        "location": "North America",
        "secondaryLocations": [],
        "workplaceType": "Hybrid",
        "employmentType": "FullTime",
        "compensation": {},
    }
    markdown, _ = _format_api_listing([job], "acme")
    assert "| Engineer \\| Senior |" in markdown
    # The title pipe is escaped, so the data row keeps the same number of
    # cells as the header (7 columns) instead of splitting into an extra one.
    header = next(line for line in markdown.splitlines() if line.startswith("| Title"))
    row = next(line for line in markdown.splitlines() if line.startswith("| Engineer"))
    assert row.count(" | ") == header.count(" | ")


def test_api_listing_escapes_newline_in_cell():
    # VAL-FU-003: a location containing a newline must render as a single
    # escaped cell rather than breaking onto a new line.
    job = {
        "id": JOB_1_UUID,
        "title": "Engineer",
        "department": "Product",
        "team": "Engineering",
        "location": "North America",
        "secondaryLocations": ["San Francisco\nCA"],
        "workplaceType": "Hybrid",
        "employmentType": "FullTime",
        "compensation": {},
    }
    markdown, _ = _format_api_listing([job], "acme")
    assert "San Francisco<br>CA" in markdown
    # Only the header (2 rows) and this job row plus blank/spacer lines; the
    # newline must not have introduced an extra table row.
    table_lines = [line for line in markdown.splitlines() if line.startswith("|")]
    assert len(table_lines) == 3  # header, separator, single data row


def test_api_job_escapes_pipe_and_newline_in_cells():
    # VAL-FU-003: individual-job detail table cells must escape pipes and
    # newlines in title/location so the table stays intact.
    job = {
        "id": JOB_1_UUID,
        "title": "Engineer\nSenior",
        "department": "Product",
        "team": "Engineering",
        "location": "NYC|Remote",
        "secondaryLocations": [],
        "workplaceType": "Hybrid",
        "employmentType": "FullTime",
        "publishedAt": "2024-01-15T10:00:00.000+00:00",
        "jobUrl": f"https://jobs.ashbyhq.com/acme/{JOB_1_UUID}",
        "descriptionHtml": "<p>Build great software.</p>",
        "compensation": {},
    }
    markdown, _ = _format_api_job(job, "acme", JOB_1_UUID)
    assert "| **Location** | NYC\\|Remote |" in markdown
    # A field with a newline must not inject a line break into the table.
    assert "| Field | Value |" in markdown


# ── Dispatch: listing vs individual (VAL-ASHBY-010) ──────────────


async def test_listing_url_uses_listing_formatter(monkeypatch):
    async def fake_fetch_board(board, include_compensation=True):
        return {"jobs": SAMPLE_JOBS, "apiVersion": 1}

    monkeypatch.setattr(mod, "_fetch_board", fake_fetch_board)
    ctx = AdapterContext(config={})
    result = await AshbyHQAdapter().scrape("https://jobs.ashbyhq.com/acme", ctx)
    assert result.success is True
    assert result.source == "ashbyhq-api"
    assert "Job Openings" in result.markdown


async def test_individual_url_uses_job_formatter(monkeypatch):
    async def fake_fetch_board(board, include_compensation=True):
        return {"jobs": SAMPLE_JOBS, "apiVersion": 1}

    monkeypatch.setattr(mod, "_fetch_board", fake_fetch_board)
    ctx = AdapterContext(config={})
    url = f"https://jobs.ashbyhq.com/acme/{JOB_1_UUID}"
    result = await AshbyHQAdapter().scrape(url, ctx)
    assert result.success is True
    assert result.source == "ashbyhq-api"
    assert "## Description" in result.markdown
    assert "Software Engineer" in result.markdown


# ── SSR fallback (VAL-ASHBY-005, VAL-ASHBY-011) ──────────────────


async def test_ssr_fallback_on_api_failure(monkeypatch):
    async def fake_fetch_board(board, include_compensation=True):
        return None

    async def fake_appdata(url):
        return SSR_JOB_DATA

    monkeypatch.setattr(mod, "_fetch_board", fake_fetch_board)
    monkeypatch.setattr(mod, "_fetch_and_parse_appdata", fake_appdata)
    ctx = AdapterContext(config={})
    url = f"https://jobs.ashbyhq.com/acme/{JOB_1_UUID}"
    result = await AshbyHQAdapter().scrape(url, ctx)
    assert result.success is True
    assert result.source in {"ashbyhq", "ashbyhq-readability"}
    assert "Software Engineer" in result.markdown


async def test_unknown_board_falls_through_to_ssr_listing(monkeypatch):
    async def fake_fetch_board(board, include_compensation=True):
        return None  # unknown board → 404

    async def fake_appdata(url):
        return SSR_LISTING_DATA

    monkeypatch.setattr(mod, "_fetch_board", fake_fetch_board)
    monkeypatch.setattr(mod, "_fetch_and_parse_appdata", fake_appdata)
    ctx = AdapterContext(config={})
    result = await AshbyHQAdapter().scrape("https://jobs.ashbyhq.com/unknownboard", ctx)
    assert result.success is True
    assert result.source == "ashbyhq-listing"
    assert "Job Openings" in result.markdown
    assert "SSR Job A" in result.markdown


# ── Authenticated RPC gating (VAL-ASHBY-006, VAL-ASHBY-007) ──────


async def test_rpc_skipped_without_api_key(monkeypatch):
    calls: list[str] = []

    async def fake_fetch_board(board, include_compensation=True):
        return {"jobs": SAMPLE_JOBS, "apiVersion": 1}

    async def fake_rpc(api_key):
        calls.append("rpc")
        return SAMPLE_RPC_RESULTS

    monkeypatch.setattr(mod, "_fetch_board", fake_fetch_board)
    monkeypatch.setattr(mod, "_fetch_rpc_jobs", fake_rpc)
    ctx = AdapterContext(config={})  # no ASHBY_API_KEY
    result = await AshbyHQAdapter().scrape("https://jobs.ashbyhq.com/acme", ctx)
    assert result.success is True
    assert result.source == "ashbyhq-api"
    assert calls == []  # RPC transport never invoked


async def test_rpc_engages_with_api_key(monkeypatch):
    calls: list[str] = []

    async def fake_fetch_board(board, include_compensation=True):
        return None  # public tier unavailable

    async def fake_rpc(api_key):
        calls.append(api_key)
        return SAMPLE_RPC_RESULTS

    monkeypatch.setattr(mod, "_fetch_board", fake_fetch_board)
    monkeypatch.setattr(mod, "_fetch_rpc_jobs", fake_rpc)
    ctx = AdapterContext(config={"ASHBY_API_KEY": "test-key"})
    url = f"https://jobs.ashbyhq.com/acme/{JOB_1_UUID}"
    result = await AshbyHQAdapter().scrape(url, ctx)
    assert result.success is True
    assert result.source == "ashbyhq-api"
    assert calls == ["test-key"]
    assert "Software Engineer" in result.markdown


async def test_rpc_not_used_for_listing_with_key(monkeypatch):
    # jobPosting.list is scoped to the key owner's company, so it must never
    # be used to render an arbitrary listing board — even when a key is set.
    calls: list[str] = []

    async def fake_fetch_board(board, include_compensation=True):
        return None  # public tier unavailable

    async def fake_rpc(api_key):
        calls.append(api_key)
        return SAMPLE_RPC_RESULTS

    async def fake_appdata(url):
        return None

    async def fake_scrape_page(url, timeout=15.0):
        return None

    monkeypatch.setattr(mod, "_fetch_board", fake_fetch_board)
    monkeypatch.setattr(mod, "_fetch_and_parse_appdata", fake_appdata)
    monkeypatch.setattr(mod, "scrape_page", fake_scrape_page)
    monkeypatch.setattr(mod, "_fetch_rpc_jobs", fake_rpc)
    ctx = AdapterContext(config={"ADAPTER_ASHBY_API_KEY": "test-key"})
    with pytest.raises(AdapterError):
        await AshbyHQAdapter().scrape("https://jobs.ashbyhq.com/other", ctx)
    assert calls == []  # RPC transport never invoked for a listing URL


# ── Registry registration + dispatch (VAL-ASHBY-012) ─────────────


def test_adapter_registered_once():
    # The shared registry list is reassigned by AdapterRegistry.load_all()
    # and mutated by other adapter tests, so reference it dynamically and
    # assert that a single import of the ashbyhq module adds exactly ONE
    # auto-registration — i.e. no duplicates.
    def _count() -> int:
        return sum(
            1 for cls in base_mod._registry_list if cls.__name__ == "AshbyHQAdapter"
        )

    baseline = _count()
    importlib.reload(importlib.import_module("scraper.adapters.ashbyhq"))
    assert _count() == baseline + 1


async def test_registry_dispatch_for_jobs_url(monkeypatch):
    async def fake_fetch_board(board, include_compensation=True):
        return {"jobs": SAMPLE_JOBS, "apiVersion": 1}

    monkeypatch.setattr(mod, "_fetch_board", fake_fetch_board)
    registry = AdapterRegistry()
    registry.register(AshbyHQAdapter())
    ctx = AdapterContext(config={})
    result = await registry.dispatch("https://jobs.ashbyhq.com/acme", ctx)
    assert result is not None
    assert result.success is True
    assert result.source == "ashbyhq-api"
    assert "Software Engineer" in result.markdown
