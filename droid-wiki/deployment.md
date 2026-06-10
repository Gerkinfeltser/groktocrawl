# Deployment

## Single-file deployment

GroktoCrawl is designed to run with a single `docker compose up --build -d`. The `docker-compose.yml` at the repo root defines all 8 core containers plus optional services.

## Production checklist

1. Set a real LLM provider in `.env`
2. Enable API key authentication: `API_KEY=sk-your-secret-key`
3. Optionally enable the politeness protocol: `SCRAPER_POLITENESS_ENABLED=true`
4. Optionally configure the scrape cache with appropriate TTLs
5. Set `LOG_LEVEL=INFO` (or WARNING for quieter logs)

## Service isolation

Only the following ports are exposed to the host:

| Service | Port |
|---|---|
| agent-svc | 8080 |
| portal-svc | 8082 |
| searxng | 8081 |
| semantic-svc | 8003 |

All other services (scraper-svc, browser-svc, parse-svc) are reachable only via Docker internal DNS.

## Proxy configuration

For production deployments behind a corporate network or requiring egress through a specific IP:

```env
SCRAPER_PROXY_URL=http://proxy:8080
```

Supported schemes: `http://`, `https://`, `socks5://`, `socks5h://`.

## Scalability

Jobs are processed inline with `asyncio.create_task()` inside the API process. For high-throughput production deployments, restore the RQ queue (reference in `app.py`) and add a separate worker container.
