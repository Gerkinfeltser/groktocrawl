# Security Policy

## Reporting a Vulnerability

GroktoCrawl is a self-hosted open source project. We take security
vulnerabilities seriously and appreciate responsible disclosure.

If you discover a security vulnerability, please report it privately by
emailing **magnus@groktop.us**.

Please do not open public GitHub issues for security vulnerabilities.

### What to Include

- A clear description of the vulnerability
- The affected component and version
- Steps to reproduce (proof of concept)
- Any suggested mitigation (optional but appreciated)

### Response Timeline

- **Acknowledgement:** Within 48 hours
- **Initial assessment:** Within 5 business days
- **Fix timeline:** Depends on severity — critical issues are typically
  resolved within a week

## Security Features

### API Authentication (v0.5.0+)

Set `API_KEY` in your `.env` file to enable bearer token authentication.
All API endpoints (except `/health`) require `Authorization: Bearer ***or `X-API-Key: <key>` headers.

When no `API_KEY` is configured, every response includes an
`X-Security-Warning` header and a structured warning in the `/health`
endpoint body. The CLI prints a one-time warning on first use.

See the [README](README.md#security) for setup instructions.

### Private Network Protection (v0.5.0+)

The browser service and scraper service block navigation to:

- **RFC 1918** private IP ranges (10.x, 172.16-31.x, 192.168.x)
- **Loopback** (127.x, ::1)
- **Link-local** (169.254.x)
- **Cloud metadata endpoints** (169.254.169.254)
- **Docker host** (*.docker.internal)

This prevents SSRF-based pivoting through the headless browser.

### Network Hardening (v0.5.0+)

Internal services (browser-svc, scraper-svc, parse-svc) no longer publish
ports to the host. They are only reachable through the agent API on port
8080 via Docker's internal DNS.

## Supported Versions

| Version | Supported |
|---------|-----------|
| 0.5.x   | ✅ |
| < 0.5   | ❌ (no auth/security features) |

## Acknowledgments

We thank the following individuals for their responsible disclosures:

- **Bertie** — Reported the unauthenticated browser pivot and private
  network SSRF vector that led to the v0.5.0 security release.
