# Debugging

## Logs

The agent service uses structured JSON logging. View logs for a specific service:

```bash
docker compose logs agent-svc
docker compose logs scraper-svc
docker compose logs semantic-svc
```

Log level is controlled by `LOG_LEVEL` env var (default: INFO). Set to `DEBUG` for verbose output.

## Common issues

### Scrape returns empty content

Check if the target site requires JavaScript. The scraper falls through tiers from llms.txt to Playwright, so content should render from Tier 3. Check `docker compose logs scraper-svc` for tier diagnostics.

### Agent returns "no sources found"

SearXNG may not be returning results. Check `docker compose logs searxng` and verify that SearXNG engines are configured. Try `curl http://localhost:8081/search?q=test&format=json` directly.

### Valkey connection refused

Ensure Valkey is healthy: `docker compose ps valkey`. The service must be healthy before agent-svc can connect.

### LLM returns errors

Verify `LLM_BASE_URL`, `LLM_API_KEY`, and `LLM_MODEL` are set correctly in `.env`. Try the LLM endpoint directly:

```bash
curl http://<llm-base-url>/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <key>" \
  -d '{"model": "<model>", "messages": [{"role": "user", "content": "hello"}]}'
```

### Security warning on every response

Set `API_KEY` in `.env` to enable authentication and silence the warning.
