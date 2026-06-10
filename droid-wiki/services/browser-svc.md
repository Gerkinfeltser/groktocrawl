# browser-svc

Active contributors: groktopus

## Purpose

The browser service manages Playwright-based headless Chromium sessions. It is used by scraper-svc for JavaScript-rendered page extraction (Tier 3) and by agent-svc for interactive browser sessions (`POST /v2/browser`).

## Directory layout

```
browser-svc/
├── Dockerfile
├── pyproject.toml
└── browser_svc/
    └── app.py    # Playwright session management
```

## Key abstractions

| Abstraction | Description |
|---|---|
| `create_browser()` | Creates a new browser session with configurable TTL |
| `execute_action()` | Executes actions: navigate, click, type, screenshot, scroll, wait, getContent, executeScript |
| Session store | In-memory map of active sessions with auto-expiry |

## How it works

Each browser context is an isolated Playwright Chromium instance. Sessions have configurable TTLs (default 300s, max 3600s). The service exposes REST endpoints that agent-svc proxies through:

- `POST /browsers` -- create a session
- `GET /browsers` -- list active sessions
- `POST /browsers/{id}/execute` -- run an action
- `DELETE /browsers/{id}` -- destroy a session

The service implements private network protection, blocking navigation to RFC 1918 addresses, loopback addresses, cloud metadata endpoints, and the Docker host machine to prevent SSRF-based pivoting.

## Integration points

- Called by scraper-svc for Tier 3 (Playwright) rendering
- Called by agent-svc's API routes via `_browser_proxy()` in `api.py`
- No host port is exposed -- reachable only via Docker internal DNS at `http://browser-svc:8012`
