# External dependencies

## Core infrastructure

| Dependency | Role | Image / URL |
|---|---|---|
| **Valkey** | Job queue, cache, and key-value storage | `valkey/valkey:8-alpine` |
| **SearXNG** | Self-hosted meta search engine | `searxng/searxng:latest` |
| **Qdrant** | Persistent vector database for semantic search | `qdrant/qdrant:v1.18.2` |
| **Playwright** | Headless Chromium for JavaScript rendering | Built into browser-svc |

## Optional infrastructure

| Dependency | Role | Image / URL |
|---|---|---|
| **FlareSolverr** | Cloudflare challenge bypass | `ghcr.io/flaresolverr/flaresolverr:latest` |
| **Ofelia** | Docker-native cron scheduler for monitors | `mcuadrados/ofelia:latest` |

## Fixture services (development only)

| Dependency | Role |
|---|---|
| **search-svc** | Mock search engine returning deterministic results |
| **llm-svc** | Mock LLM returning predictable responses |
| **test-site** | Fixture website with known content for integration tests |

## LLM providers

Any OpenAI-compatible API works. Tested options:

| Provider | Base URL |
|---|---|
| **DeepSeek** | `https://api.deepseek.com/v1` |
| **OpenAI** | `https://api.openai.com/v1` |
| **Ollama** (local) | `http://host.docker.internal:11434/v1` |
| **OpenRouter** | `https://openrouter.ai/api/v1` |

## Python package dependencies

### agent-svc

`fastapi`, `uvicorn`, `rq`, `redis`, `httpx`, `pydantic`, `beautifulsoup4`, `python-multipart`

### scraper-svc

`fastapi`, `uvicorn`, `httpx`, `readability-lxml`, `markdownify`, `beautifulsoup4`, `redis`, `youtube_transcript_api`
Optional: `playwright`, `crawl4ai`

### semantic-svc

`fastapi`, `uvicorn`, `qdrant-client`, `sentence-transformers`, `numpy`, `httpx`
