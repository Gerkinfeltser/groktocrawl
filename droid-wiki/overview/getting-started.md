# Getting started

## Prerequisites

- Docker and Docker Compose (v2)
- Git
- An LLM API key (optional for development, required for production use)

## Quick start

```bash
git clone https://github.com/groktopus/groktocrawl
cd groktocrawl
cp .env.sample .env
docker compose up --build -d
```

This starts all 8 core containers. Once running, verify health:

```bash
curl http://localhost:8080/health
```

Expected response:

```json
{"status": "ok", "checks": {"valkey": {...}, "searxng": {...}, "scraper": {...}, "browser": {...}}}
```

## Using the CLI

The `groktocrawl` CLI script in the repo root requires the `requests` library:

```bash
pip install requests
./groktocrawl scrape https://example.com
./groktocrawl search "raspberry pi 5" --limit 3
./groktocrawl agent "What were the key Google I/O 2025 announcements?"
```

Or use raw curl:

```bash
curl -X POST http://localhost:8080/v2/scrape \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com"}'
```

## Production setup

Edit `.env` to point at a real LLM provider:

```env
LLM_API_KEY=sk-your-key
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_MODEL=deepseek-v4-flash
```

Set an API key for authentication:

```env
API_KEY=sk-your-secret-key-here
```

## Running tests

```bash
cp .env.sample .env
docker compose up --build -d
docker compose exec agent-svc python3 /app/agent/tests/test_stack.py
```

This runs the full integration test suite against the live Docker stack.
