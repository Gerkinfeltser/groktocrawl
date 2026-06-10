# Authentication and security

Active contributors: groktopus

## Purpose

GroktoCrawl provides optional API key authentication and built-in SSRF protection to secure production deployments.

## How it works

### API key authentication

Authentication is controlled by the `API_KEY` environment variable:

- **When `API_KEY` is set**: all API calls (except `/health` and `/metrics`) require `Authorization: Bearer <key>` or `X-API-Key: <key>` header
- **When `API_KEY` is not set**: the API is fully open (backward compatible mode). A security warning header is added to every response

The `verify_api_key()` FastAPI dependency in `agent-svc/agent/auth.py` checks both the `Authorization: Bearer` and `X-API-Key` headers. Unauthenticated requests to protected endpoints receive a 403 response.

### Security warning

When auth is disabled, every response includes an `X-Security-Warning` header and the `/health` endpoint adds a `security` field in the response body warning that the API is publicly accessible.

### Private network protection

All internal services (scraper-svc, browser-svc, parse-svc) are reachable only via Docker internal DNS -- they do not publish host ports. The only host-exposed ports are:

| Service | Port |
|---|---|
| agent-svc | 8080 |
| portal-svc | 8082 |
| searxng | 8081 |
| semantic-svc | 8003 |

### SSRF protection

The scraper and browser services block navigation to:

- Private IP ranges (RFC 1918: 10.x.x.x, 172.16-31.x.x, 192.168.x.x)
- Loopback addresses (127.x.x.x, ::1)
- Cloud metadata endpoints (e.g., 169.254.169.254)
- Docker host machine

This applies to both direct URLs and resolved hostnames (DNS rebinding protection).

### Vulnerability reporting

See [SECURITY.md](../../SECURITY.md) for the disclosure policy.

## Key source files

| File | Purpose |
|---|---|
| `agent-svc/agent/auth.py` | API key verification, security warning labels |
| `agent-svc/agent/app.py` | Security warning middleware |
| `scraper-svc/scraper/fetch.py` | IP blocklist enforcement |
