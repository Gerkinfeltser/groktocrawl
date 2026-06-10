# Configuration

GroktoCrawl is configured through environment variables in `.env`. Below is the full reference organized by concern.

## LLM provider

| Variable | Default | Description |
|---|---|---|
| `LLM_API_KEY` | (empty) | API key for the LLM provider |
| `LLM_BASE_URL` | `http://llm-svc:8011/v1` | OpenAI-compatible endpoint |
| `LLM_MODEL` | `deepseek-v4-flash` | Model name to use |
| `LLM_ENABLE_THINKING` | `false` | Enable thinking/reasoning for supported models |
| `WEBHOOK_SECRET` | (empty) | HMAC secret for webhook payload signing |

## API security

| Variable | Default | Description |
|---|---|---|
| `API_KEY` | (empty) | When set, requires Bearer token on all endpoints except /health and /metrics |

## Service URLs

| Variable | Default | Description |
|---|---|---|
| `VALKEY_URL` | `redis://valkey:6379/0` | Valkey connection string |
| `SEARXNG_URL` | `http://searxng:8080` | SearXNG search engine URL |
| `SCRAPER_URL` | `http://scraper-svc:8001` | Scraper service URL |
| `SEMANTIC_URL` | `http://semantic-svc:8003` | Semantic service URL |
| `QDRANT_URL` | `http://qdrant:6333` | Qdrant vector database URL |

## Vector index

| Variable | Default | Description |
|---|---|---|
| `VECTOR_INDEX_MAX_DOCS` | 250000 | Maximum documents before eviction |
| `EMBED_MODEL_NAME` | `BAAI/bge-m3` | Embedding model name |
| `EMBED_DIM` | 1024 | Embedding dimension (must match model) |
| `ACTIVE_EMBED_MODEL` | `v_bge-m3` | Active named vector for queries |

## Near-duplicate detection

| Variable | Default | Description |
|---|---|---|
| `NEAR_DUP_THRESHOLD` | 0.95 | Cosine similarity threshold |
| `NEAR_DUP_MODE` | `skip` | Behavior: "skip" or "update" |

## Scrape cache

| Variable | Default | Description |
|---|---|---|
| `SCRAPE_CACHE_TTL` | 3600 | Global cache TTL (seconds) |
| `SCRAPE_CACHE_MIN_TTL` | 60 | Minimum cache TTL |
| `SCRAPE_CACHE_MAX_TTL` | 86400 | Maximum cache TTL |
| `SCRAPE_CACHE_STABLE_MULTIPLIER` | 2.0 | TTL multiplier for unchanged content |
| `SCRAPE_CACHE_VOLATILE_CAP` | 300 | TTL cap for volatile content (change_count >= 5) |
| `SCRAPE_CACHE_DOMAIN_TTLS` | (empty) | JSON dict of domain -> TTL overrides |

## Politeness protocol

| Variable | Default | Description |
|---|---|---|
| `SCRAPER_POLITENESS_ENABLED` | `false` | Enable per-domain rate limiting |
| `SCRAPER_POLITENESS_CRAWL_DELAY` | 1.0 | Minimum delay between requests (seconds) |
| `SCRAPER_POLITENESS_ROBOTS_TTL` | 3600 | robots.txt cache TTL |

## Proxy

| Variable | Default | Description |
|---|---|---|
| `SCRAPER_PROXY_URL` | (empty) | Outbound proxy URL (http, https, socks5, socks5h) |

## Quality gates

| Variable | Default | Description |
|---|---|---|
| `QA_MIN_CONTENT_CHARS` | 200 | Minimum content characters |
| `QA_MIN_TITLE_CHARS` | 10 | Minimum title characters |
| `QA_MAX_BOILERPLATE_RATIO` | 0.7 | Maximum boilerplate-to-content ratio |
| `QA_MIN_QUALITY_THRESHOLD` | 0.3 | Quality score threshold for tier degradation |

## Adapters

| Variable | Default | Description |
|---|---|---|
| `GITHUB_TOKEN` | (empty) | GitHub API token (5,000 req/hr vs 60 unauth) |
| `ADAPTER_YOUTUBE_API_KEY` | (empty) | YouTube Data API v3 key (optional) |
| `BRAVE_API_KEY` | (empty) | Brave Search API key for SearXNG |

## Logging

| Variable | Default | Description |
|---|---|---|
| `LOG_LEVEL` | `INFO` | Root logger level (INFO, DEBUG, WARNING, ERROR) |

## FlareSolverr

| Variable | Default | Description |
|---|---|---|
| `FLARE_SOLVERR_URL` | `http://flare-solverr:8191/v1` | FlareSolverr endpoint |
| `FLARE_SOLVERR_PORT` | 8191 | Host port for FlareSolverr |
| `FLARE_SOLVERR_LOG_LEVEL` | `info` | FlareSolverr log level |
| `FLARE_SOLVERR_CAPTCHA_SOLVER` | `none` | CAPTCHA solver backend |
