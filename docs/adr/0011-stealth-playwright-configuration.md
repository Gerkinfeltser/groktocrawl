# Stealth Playwright Configuration for Anti-Detection

* Status: accepted
* Deciders: magnus, jasper
* Date: 2026-06-05

Technical Story: Headless Playwright browsers are trivially detectable by Cloudflare, DDoS-Guard, Substack, and other anti-bot services. The original scraper used a bare Playwright launch with no stealth configuration, resulting in immediate blocks on most JS-heavy sites.

## Context and Problem Statement

The scraper relies on Playwright (via Tier 3) to render JavaScript-heavy pages and extract content. Without stealth configuration:

1. **`navigator.webdriver` is `true`** — the single strongest signal that a browser is automated
2. **Chrome headless fingerprints** — `User-Agent` contains `HeadlessChrome`, viewport is default 800x600
3. **No locale/timezone/geolocation** — Real browsers always set these; absence is suspicious
4. **Bot challenge pages are returned as content** — Cloudflare JS challenges resolve only for real browsers

The same stealth configuration is maintained in two places: `browser-svc/browser_svc/app.py` (for browser-svc sessions) and `scraper-svc/scraper/fetch.py` → `scraper-svc/scraper/stealth.py` (for the scraper's inline Playwright).

## Decision Drivers

* Must reduce the detectable surface area between headless and headed Chromium
* Must not require external npm packages (playwright-stealth, puppeteer-extra-stealth)
* Must be maintainable in two locations (scraper-svc inline and browser-svc) without drift
* Bot challenge detection must be heuristic-based, not dependent on solving the challenge

## Considered Options

* **A. Manual stealth configuration** — Set User-Agent, Chromium args, viewport, locale, timezone, permissions, and navigator.webdriver override manually. The current implementation.
* **B. playwright-stealth npm plugin** — Use the well-known `playwright-stealth` plugin for comprehensive evasion.
* **C. No stealth (accept blocks)** — Let the generic pipeline fail and rely entirely on adapters for anti-bot sites.

## Decision Outcome

Chosen option: **A. Manual stealth configuration**, because it requires no external dependencies, gives full control over the evasion surface, and keeps the deployment simple (no npm in a Python FastAPI container).

### Stealth Configuration Details

**Chromium launch args:**
```
--disable-blink-features=AutomationControlled
--no-sandbox
--disable-dev-shm-usage
```

**Browser context configuration:**
- `viewport`: 1920×1080
- `user_agent`: Chrome 131 on Windows 10 (real-looking, non-headless)
- `locale`: "en-US"
- `timezone_id`: "America/New_York"
- `permissions`: ["geolocation"]

**Init script (executed before every page load):**
```js
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
```

**Bot challenge detection (Cloudflare + DDoS-Guard):**
- Page title checked against known challenge indicators
- URL checked for `cf_chl`, `challenge-platform`, `ddos-guard` patterns
- After detection: 8-second wait for JS challenge resolution
- If challenge persists after wait: logged and content returned as-is

### Positive Consequences

* Zero external dependencies for stealth
* Full control — can add/remove evasion techniques without upstream changes
* Anti-detection surface is inspectable and auditable

### Negative Consequences

* Duplicated between scraper-svc and browser-svc — risk of drift. Mitigated by shared `stealth.py` module in scraper-svc and inline code in browser-svc with same constants
* Less comprehensive than dedicated stealth plugins (no WebGL/Canvas fingerprint spoofing)
* Manual maintenance — must update Chrome user-agent when browser versions advance

## Links

* Refined by [ADR-0010: Five-Tier Scraper Pipeline](0010-five-tier-scraper-with-llm-recovery.md) — Tier 3 depends on stealth for Playwright success
* See [ADR-0013: Cloudflare Cookie Persistence](0013-cloudflare-cookie-persistence.md) — cookie persistence complements stealth
