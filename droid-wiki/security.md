# Security

## API authentication

Optional bearer token authentication is controlled by the `API_KEY` environment variable. When set, all endpoints except `/health` and `/metrics` require `Authorization: Bearer <key>` or `X-API-Key: <key>`.

When no key is configured, the API is fully open with a security warning on every response. See [Authentication and security](features/auth-security.md) for details.

## SSRF protection

The built-in browser and scraper services block navigation to:

- Private IP ranges (RFC 1918)
- Loopback addresses
- Cloud metadata endpoints (169.254.169.254, etc.)
- Docker host machine

This prevents SSRF-based pivoting through the headless browser. The blocklist applies to both direct URLs and resolved hostnames (DNS rebinding protection).

## Service architecture

Internal services (browser-svc, scraper-svc, parse-svc) do not publish host ports. Only the agent API is exposed to the host. All internal requests route through the agent API.

## Webhook signing

When `WEBHOOK_SECRET` is set, webhook payloads are signed with HMAC-SHA256 and delivered with an `X-Webhook-Signature` header.

## Vulnerability reporting

See [SECURITY.md](https://github.com/groktopus/groktocrawl/blob/main/SECURITY.md) for the disclosure policy and how to privately report security issues.
