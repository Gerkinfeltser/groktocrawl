# Proxy Support for Egress Routing (SCRAPER_PROXY_URL)

* Status: accepted
* Deciders: magnus, jasper
* Date: 2026-06-06

Technical Story: Issue #127 requests a `SCRAPER_PROXY_URL` env var plumbed through the httpx clients (Tiers 1-2) and Playwright browser context (Tier 3), enabling Groktocrawl to route outbound scrape requests through a proxy. The author has a working implementation (~10 lines) and offered to PR.

## Context and Problem Statement

Groktocrawl's five-tier scrape pipeline (adapters → llms.txt → content negotiation → Playwright stealth → FlareSolverr) handles detection-method blocking — browser fingerprinting, JS challenges, CAPTCHAs — but has no mechanism for IP-origin blocking. A user behind a datacenter IP, corporate NAT, CGNAT, or geo-restricted network may have perfect browser fingerprinting evasion and still be blocked because the exit IP itself is on every blocklist.

Firecrawl v2 supports proxy configuration natively. As a self-hosted alternative, Groktocrawl has a parity gap.

Additionally, corporate environments often require all outbound HTTP traffic to route through an egress proxy. A self-hosted service deployed behind a corporate NAT that cannot be configured for outbound proxy routing is operationally unreachable for those users.

## Decision Drivers

* Must preserve existing behavior for users who do not set the proxy env var — zero behavioral change by default
* Proxy failures must not silently degrade scrape quality — operators must be able to distinguish "proxy gave wrong content" from "site changed content"
* Must be a single env var (one proxy URL), not a pool management system — rotation belongs in an orchestration layer above Groktocrawl
* Proxy credentials must not leak into error logs or process listings
* The change must be minimal in code surface area — the ~10 line estimate from the contributor is the right scale
* Must work across all three transport tiers: llms.txt fetch (httpx), content negotiation fetch (httpx), and Playwright browser context

## Considered Options

* **A. Single SCRAPER_PROXY_URL env var** — One env var, plumbed through httpx clients (Tiers 1-2) and Playwright browser context (Tier 3). Fail open with WARN on proxy failure.
* **B. Documented workaround** — No code change. Document that users can set `HTTP_PROXY`/`HTTPS_PROXY` env vars at the container level (which httpx respects natively) and that Playwright proxy is a manual configuration concern.
* **C. Proxy pool / rotation system** — Built-in support for multiple proxies, rotation policies, health checking, and geo-targeting. Significantly larger scope.

## Decision Outcome

Chosen option: **A. Single SCRAPER_PROXY_URL env var**, because:

1. It fills a genuine structural gap (IP-origin blocking is orthogonal to all five existing tiers)
2. The implementation surface is bounded (~10-30 lines)
3. A single env var is the gold standard for deployment topology flexibility — it works identically across Docker env_file, K8s secrets, Ansible vars, and systemd unit files
4. It is trivially absent when unset — no behavioral change for users who don't need it
5. The author has a working, production-tested implementation that validates the approach

Option B was rejected because standard `HTTP_PROXY` env vars are not inherited by Playwright browser contexts consistently, and leaving Playwright without proxy support would leave the most important tier uncovered. Option C was rejected because proxy pool management is a separate concern that belongs above Groktocrawl (HAProxy, Scrapoxy, rotating pool frontend), not embedded in a scraping tool.

### Guardrails

The following guardrails are non-negotiable for merge:

1. **Opt-in only via env var** — users who don't set `SCRAPER_PROXY_URL` see zero behavioral change
2. **Per-scrape proxy identity logging** — every scrape log line emitted on a proxied request must record which proxy was used (host:port, without credentials) so operators can distinguish "proxy returned stale data" from "the site's content actually changed"
3. **Fail open with WARN** — if the proxy is unreachable or returns an error, retry the request without proxy and log the fallback at WARN level. Never cascade silently into bad data.
4. **Single static proxy** — exactly one proxy URL. No rotation, no pool management, no geo-targeting. Users who need multiple proxies should front Groktocrawl with a rotating proxy orchestrator.

### Architectural Placement

Proxy support is not a "sixth tier" in the scrape pipeline sequence. It is a **transport-layer modifier** that operates orthogonally to the existing five tiers:

```
Request → [SCRAPER_PROXY_URL check] → [Tier 1: Adapters] → [Tier 2: llms.txt] → [Tier 3: Content negotiation] → [Tier 4: Playwright stealth (via context proxy)] → [Tier 5: FlareSolverr] → Response
```

The proxy is applied at the transport layer before any tier executes. If a tier fails due to an IP-origin block, the proxy does not retry that tier — it is the transport for the tier's request. The fail-open behavior means a failed proxy connection falls through to a direct connection for that request.

### Playwright Implementation Details

The Playwright proxy must use **context-level assignment** (`browser.new_context(proxy={"server": "...", "username": "...", "password": "..."})`) rather than **launch-level args** (`browser.launch(args=["--proxy-server=..."])`). Context-level assignment provides:

- Per-isolation — each scrape job gets its own proxy context, unrelated to others
- No conflict with existing stealth browser launch args (`--disable-web-security`, `--no-sandbox`)
- Clean teardown — proxy config is scoped to the context lifecycle

### Security

- Proxy credentials in the env var URL (`http://user:pass@host:port`) must be redacted from all log output. Log only `proxy_host=host:port`, never the full URL.
- The env var must support standard URI schemes: `http://`, `https://`, `socks5://`, `socks5h://`.
- No proxy auth secrets may appear in process listings or error telemetry.

### Consequences

*Good:*
- Groktocrawl becomes deployable behind corporate NAT gateways, residential proxy pools, and geo-restricted networks
- Parity with Firecrawl v2 proxy support
- The change is opt-in and bounded — no regression for existing users
- The single env var pattern matches standard deployment conventions (Docker, K8s, systemd)

*Neutral:*
- Proxy adds a new failure mode (silent data corruption through a bad proxy). This is mitigated by the per-scrape logging and fail-open guardrails.
- Documentation needed: one paragraph in README covering env var name, tier effect, and guardrails

*Risks:*
- Proxy credentials may leak into error telemetry if not scrubbed at the logging boundary. Mitigated by the security requirement above.
- Users may request proxy rotation, pool management, or geo-targeting follow-up features. Mitigated by explicitly documenting these as out of scope in the feature.
- The fail-open default means users behind a corporate proxy that requires all egress to route through it may bypass that policy on proxy failure. A future enhancement could add a configurable `SCRAPER_PROXY_FAIL_CLOSED` flag.

## Links

- [Issue #127: feat: proxy support + external browser adapter for anti-bot sites](https://github.com/groktopus/groktocrawl/issues/127)
- [PR #121: Reddit JSON API adapter](https://github.com/groktopus/groktocrawl/pull/121)
- [ADR-0010: Five-Tier Scraper Pipeline with LLM-Assisted Recovery](0010-five-tier-scraper-with-llm-recovery.md)
