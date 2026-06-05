# Barrier Classification Phase 1

* Status: accepted
* Deciders: magnus, jasper
* Date: 2026-06-05

Technical Story: The scraper pipeline used a boolean `_looks_suspicious()` heuristic to detect bot challenges and error pages. This provided no actionable detail — the caller could not distinguish Cloudflare CAPTCHAs from empty responses, rate limits from Substack redirects, or low-confidence signals from high-confidence ones.

## Context and Problem Statement

When the scraper encounters a URL behind a bot protection service (Cloudflare, DDoS-Guard), a CAPTCHA wall, a rate-limit page, or a redirect to a non-content frame (Substack), the HTML-to-markdown pipeline produces either empty output, a challenge page rendered as garbled text, or a frame redirect instead of the actual content. The pipeline's downstream logic (LLM recovery, browser-svc fallback) has no structured information about *what kind* of barrier it hit.

The existing `_looks_suspicious()` function returned only a boolean:

```python
def _looks_suspicious(content: str) -> bool:
    """Heuristic: does the page content look like a challenge/error page?"""
```

This forced all downstream code to guess. Substack redirect detection was handled as a special case in `smart_scrape()`, Cloudflare detection was duplicated in `_is_bot_challenge()` and `_looks_suspicious()`, and there was no way to tie confidence to a specific barrier type.

## Decision Drivers

* Classify *what kind* of barrier was hit, not just whether one was hit
* Return a confidence score so the pipeline can make risk-adjusted decisions
* Keep classification lightweight — no external APIs or full HTML parsing
* Reuse existing indicator lists (CLOUDFLARE_INDICATORS, DDOS_GUARD_INDICATORS, SUBSTACK_REDIRECT_PATTERNS)
* Replace both `_looks_suspicious()` and the implicit barrier logic in each fetch function

## Considered Options

* **A. Structured classification with BarrierInfo dataclass** — A single `_classify_barrier()` function that inspects title, URL, markdown content, and raw HTML, then returns a `BarrierInfo` with detected flag, barrier type, confidence, and detail.
* **B. Extend _looks_suspicious to return a string** — Change the return type from bool to `str | None` for the barrier type. Simpler but loses confidence and structured detail.
* **C. Per-barrier-type boolean flags** — Separate functions like `_is_cloudflare()`, `_is_captcha()`, `_is_rate_limited()`. Cleaner separation but requires callers to check multiple functions.

## Decision Outcome

Chosen option: **A. Structured classification with BarrierInfo dataclass**.

A single `BarrierInfo` dataclass captures the complete classification result:

```python
@dataclass
class BarrierInfo:
    detected: bool
    barrier_type: str | None  # "cloudflare", "ddos-guard", "captcha", "rate-limit", "substack-redirect", "empty", "suspicious", None
    confidence: float
    detail: str = ""
    title: str = ""
```

The `_classify_barrier(title, url, content, html)` function checks multiple signal categories:

| Signal | Source | Trigger |
|--------|--------|---------|
| Empty content | content length | `< 100` characters |
| Cloudflare (title) | title | CLOUDFLARE_INDICATORS match |
| Cloudflare (title explicit) | title | "Attention Required" / "403 Forbidden" |
| Cloudflare (URL) | URL | `cf_chl` / `challenge-platform` |
| DDoS-Guard (title) | title | DDOS_GUARD_INDICATORS match |
| DDoS-Guard (URL) | URL | `ddos-guard` in URL |
| Captcha | content | "hcaptcha" / "recaptcha" |
| Rate-limit | content | "rate limit" / "too many requests" |
| Substack redirect | URL + html | SUBSTACK_REDIRECT_PATTERNS |
| Content fallback | content | Indicator words in markdown |

Confidence is scored by the number of distinct signal groups matched:
- 1 signal → 0.70 confidence
- 2 signals → 0.85 confidence
- 3+ signals → 0.95 confidence

The primary barrier type is determined by the highest-priority signal group.

### Wiring into the fetch pipeline

Each fetch function (`fetch_via_playwright`, `fetch_via_flaresolverr`, `_fetch_via_browser_svc`) calls `_classify_barrier()` on its result *before* returning. If the barrier is detected with confidence > 0.7, the function returns a structured error dict:

```json
{
  "error": "Barrier detected: cloudflare (confidence: 0.85)",
  "barrier": {
    "detected": true,
    "type": "cloudflare",
    "confidence": 0.85,
    "detail": "Matched signals: cloudflare-title, empty"
  },
  "markdown": "",
  "source": "barrier-detection",
  "url": "https://example.com"
}
```

In `smart_scrape()`, after each tier, the result dict is checked for a `"barrier"` key. When a barrier is detected with confidence > 0.7, all remaining tiers are skipped and the barrier error is returned immediately.

### Positive Consequences

* Downstream code (LLM recovery, browser-svc fallback) knows exactly what kind of barrier was hit
* Confidence scores enable risk-adjusted decisions (e.g., threshold tuning)
* All barrier detection is unified in one function — no duplicated logic
* The old `_looks_suspicious()` is fully replaced

### Negative Consequences

* The barrier type string is a free-text enum — no type safety on the string value
* Confidence scoring is a simple heuristic (signal count) — may need tuning in Phase 2

## Links

* Supersedes the implicit barrier detection previously spread across `_looks_suspicious()`, `_is_bot_challenge()`, and `smart_scrape()`
* Defined by `scraper-svc/scraper/fetch.py` (`BarrierInfo`, `_classify_barrier`)
* See GitHub issues #51 (barrier detection) and #99 (adaptive barrier handling)
* Phase 2 will add per-barrier-type retry strategies and configurable confidence thresholds
