# Site adapters

Active contributors: groktopus

## Purpose

Site adapters provide optimized content extraction for specific websites. They run before the generic tier pipeline and can handle JavaScript-heavy sites, API-accessible content, and structured data formats that the generic pipeline struggles with.

## Architecture

The adapter framework in `scraper-svc/scraper/adapters/base.py` provides:

- **`SiteAdapter`** -- abstract base class that each adapter implements
- **`AdapterResult`** -- structured result with markdown, metadata, and source
- **`AdapterContext`** -- framework-provided resources (config, logging, timeout helpers)
- **`AdapterRegistry`** -- loads adapters, dispatches by URL pattern matching
- **`@adapter` decorator** -- auto-registration at module import time
- **`AdapterError`** and **`AdapterTimeoutError`** -- typed error handling

Adapters define `patterns` (list of regex strings) and `priority` (integer, lower runs first). When a URL matches multiple patterns, the highest-priority adapter handles it.

## Available adapters

### YouTube adapter (`youtube.py`)

Priority 200. Handles `youtube.com/watch` and `youtu.be/*` URLs.

Returns YAML frontmatter (video_id, title, channel, thumbnail) and full video transcript as markdown. Fallback chain: `youtube_transcript_api` (free, no key) to browser render.

Configuration: `ADAPTER_YOUTUBE_API_KEY` (optional, for richer metadata).

### GitHub File adapter (`github.py`)

Priority 200. Handles raw files, blob URLs, repo roots, and tree listings on `github.com`.

Returns structured markdown with YAML frontmatter (owner, repo, stars, forks, language). Uses `raw.githubusercontent.com` direct fetch as primary strategy with GitHub Contents API as fallback. Extension allowlist for binary detection.

### GitHub Social adapter (`github_social.py`)

Priority 190. Handles issues, PRs, discussions, releases, and commits.

Fallback chain: GitHub GraphQL API (v4) to REST API to HTML page scrape. Configuration: `GITHUB_TOKEN` enables 5,000 req/hr and GraphQL access (vs 60 req/hr unauthenticated).

| URL Type | Data Returned |
|---|---|
| Issues | Body, comments, labels, state, milestone |
| Pull requests | Body, reviews, diff stats, changed files, merge status |
| Discussions | Category, upvotes, answer, comments |
| Releases | Release notes, assets, download URLs |
| Commits | Message, author, associated PRs |

### Bluesky adapter (`bluesky.py`)

Handles `bsky.app/profile/*/post/*` URLs. Returns YAML frontmatter (author, handle, did, post_id, timestamp, engagement counts) and post text with thread replies. Uses the AT Protocol XRPC API (public, no auth required).

### Substack adapter (`substack.py`)

Handles `*.substack.com` URLs and vanity domains. Returns YAML frontmatter (title, author, publication, published_date) with full article body. Fallback chain: RSS feed to readability-lxml extraction to browser render. Vanity domain detection probes `{domain}/feed` for the Substack RSS generator tag, cached per-domain for 1 hour.

## Adding a new adapter

1. Create `scraper-svc/scraper/adapters/<site>.py`
2. Subclass `SiteAdapter`, set `name`, `patterns`, `priority`
3. Implement `scrape()` returning `AdapterResult`
4. Decorate with `@adapter` for auto-registration
5. Add dependencies to `scraper-svc/pyproject.toml`
6. Add env vars to `.env.sample` and document here

## Key source files

| File | Purpose |
|---|---|
| `scraper-svc/scraper/adapters/base.py` | Framework: base class, registry, decorator |
| `scraper-svc/scraper/adapters/youtube.py` | YouTube transcript extraction |
| `scraper-svc/scraper/adapters/github.py` | GitHub file/README/directory content |
| `scraper-svc/scraper/adapters/github_social.py` | GitHub issues/PRs/discussions/releases |
| `scraper-svc/scraper/adapters/bluesky.py` | Bluesky post content |
| `scraper-svc/scraper/adapters/substack.py` | Substack article extraction |
