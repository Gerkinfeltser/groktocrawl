# scraper-svc

Active contributors: groktopus

## Purpose

The scraper service converts URLs to clean markdown using a multi-tier strategy. It runs as a FastAPI application with a single `POST /scrape` endpoint and is the foundation of all content extraction in GroktoCrawl.

## Directory layout

```
scraper-svc/
├── Dockerfile
├── pyproject.toml
└── scraper/
    ├── app.py           # FastAPI app, /scrape + /scrape/meta endpoints
    ├── fetch.py         # smart_scrape() -- three-tier pipeline
    ├── extract.py       # HTML to markdown + content quality gates
    ├── metadata.py      # JSON-LD, OpenGraph, meta tag extraction
    ├── politeness.py    # Optional robots.txt respect + rate limiting
    ├── recovery.py      # LLM-based tier 4 recovery
    ├── stealth.py       # Playwright stealth configuration
    ├── cookie_store.py  # Persistent cookie jar
    ├── meta.py          # Lightweight meta tag fetch (one GET)
    └── adapters/        # Site-specific content handlers
        ├── base.py      # Adapter registry, base class, @adapter decorator
        ├── youtube.py   # YouTube transcript + metadata
        ├── github.py    # GitHub file/README/directory content
        ├── github_social.py  # GitHub issues, PRs, discussions, releases
        ├── bluesky.py   # Bluesky post content
        └── substack.py  # Substack article content
```

## Key abstractions

| Abstraction | File | Description |
|---|---|---|
| `smart_scrape()` | `scraper/fetch.py` | Main entry point: adapter dispatch, tier pipeline, quality gates |
| `QualityGateResult` | `scraper/extract.py` | Composite quality score (0.0-1.0) with per-gate breakdown |
| `SiteAdapter` | `scraper/adapters/base.py` | Abstract base class for site-specific handlers |
| `AdapterRegistry` | `scraper/adapters/base.py` | Loads and dispatches adapters by URL pattern matching |
| `adapter()` | `scraper/adapters/base.py` | Decorator for auto-registering adapter classes |
| `PolitenessEnforcer` | `scraper/politeness.py` | Per-domain rate limiter with robots.txt caching |

## How it works

### Three-tier scraping pipeline

Tiers run sequentially, each falling through to the next on failure or low quality:

1. **Tier 1 (llms.txt)**: fetches `/llms.txt` at the site root -- one GET, potentially the whole site in markdown
2. **Tier 2 (content negotiation)**: requests the URL with `Accept: text/markdown` header
3. **Tier 3 (Playwright rendering)**: launches headless Chromium via Playwright, extracts with readability-lxml
4. **Tier 3.5 (FlareSolverr)**: routes through FlareSolverr for Cloudflare challenge bypass
5. **Tier 4 (LLM recovery)**: sends raw HTML to an LLM for extraction when all other tiers fail

### Adapter dispatch

Before any tier runs, the adapter registry checks if the URL matches a registered handler. Adapters are dispatched by regex pattern with priority ordering. When a match is found, the adapter runs its own fallback chain. If the adapter fails, the standard tier pipeline runs as normal.

Adapters auto-register via the `@adapter` decorator and `AdapterRegistry.load_all()` scans the adapters package on startup.

### Quality gates

After extraction, `assess_quality()` in `extract.py` runs three checks:
1. **Boilerplate detection** -- link density and paragraph quality analysis
2. **Completeness check** -- requires minimum content and title length
3. **Block page detection** -- pattern matching against 40+ block page signatures

The composite score is returned in the response and can trigger pipeline degradation to the next tier.

### Caching

Scrape results are cached in Valkey with freshness-aware revalidation. The cache stores ETag and Last-Modified headers for conditional revalidation. Content-change detection with SHA-256 hashing enables TTL adjustment based on volatility. Per-domain TTL overrides are configurable via `SCRAPE_CACHE_DOMAIN_TTLS`.

## Integration points

- Called by agent-svc's `ScraperClient` for all content extraction
- Calls into browser-svc for Playwright rendering
- Calls into FlareSolverr for Cloudflare bypass
- Calls into LLM for tier-4 recovery
- Uses Valkey for cache and politeness state

## Entry points for modification

To add a new adapter, create a file in `scraper/adapters/`, subclass `SiteAdapter`, set `name`, `patterns`, and `priority`, and decorate with `@adapter`. Auto-registration handles the rest. To modify the scrape pipeline, edit `smart_scrape()` in `fetch.py`.
