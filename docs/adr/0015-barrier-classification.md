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

## Amendment: Fastly challenge detection and consumer refusal (#586, 2026-08)

Nature.com (and other Fastly-fronted sites) serve a JavaScript-challenge
interstitial that Playwright renders into plausible-looking prose — the page is
non-empty, so none of the original signals fire, and the challenge text flows
through extraction as if it were article content. GitHub issue #586 closes this
gap with two additions to classification plus an enforcement invariant on every
consumer of scraper output.

### Fastly signals

`FASTLY_CHALLENGE_INDICATORS` adds the observed interstitial prose:
"JavaScript is disabled in your browser.", "Please enable JavaScript to
proceed.", and "A required part of this site couldn't load." A definitive
transport signature, `/_fs-ch-` (Fastly's challenge asset prefix), identifies
the challenge infrastructure regardless of rendered text.

### Definitive signatures vs. prose signals

Two evidence classes are now distinguished:

* **Definitive transport signature** — HTML containing `/_fs-ch-`
  short-circuits classification immediately: `BarrierInfo(detected=True,
  barrier_type="fastly", confidence=0.95)`, mirroring the captcha-provider
  block. The asset prefix is issued by Fastly's own challenge machinery; its
  presence is not plausibly legitimate content.
* **Prose signals** — the marker sentences accumulate through the existing
  count-based ladder (`min(0.50 + n * 0.20, 0.95)`): 1 signal → 0.70,
  2 signals → 0.90. Prose alone must **never** auto-classify at 0.95: wording
  can legitimately appear in articles about browsers or accessibility, so only
  the transport signature carries definitive weight.

Fastly prose-in-title and signature-bearing URLs also feed `_is_bot_challenge()`,
so the Tier 3 resolution poll engages for Fastly challenges exactly as it does
for Cloudflare.

### Consumer-refusal consequence

Detection alone proved insufficient: a classified barrier can still survive as
a "successful" scrape payload (warning key set, or quality
`block_detected ∈ {warn, fail}`), and any consumer that feeds scraper markdown
to the LLM would ingest challenge text. The enforced invariant is:

> **Barrier content must NEVER reach the LLM.**

Every agent-svc seam that ingests scraper results refuses flagged payloads
(shared predicate `agent/barrier_guard.py::is_barrier_flagged`; refusal is
logged, never silently swallowed):

* `scraper_client.scrape_with_fallback` — both stages apply the guard; when
  both stages yield only flagged content an explicit `BARRIER_DETECTED`
  failure dict is returned instead of the flagged success.
* `research/discovery._scrape_single` / `_scrape_urls` — flagged sources are
  dropped (not ingested), including re-gating of poisoned scrape-cache hits.
* Rich search (`research/search.py`) and its streaming variant — flagged
  scrapes fall back to the search-result description; no challenge markdown
  enters synthesis context.
* Answer rerank-reuse seam (`_scrape_answer_sources`) — reuse artifacts whose
  recovered markdown trips the block-page gate are refused.
* Crawler — barrier-flagged pages are recorded as errors/skips with bounded
  retries (max 2); children of such pages are not enqueued.
* Batch-scrape worker and session agent steps — flagged payloads become typed
  errors; flagged pages are never indexed.

A page that merely *quotes* the exact marker phrases is expected to be flagged
under this strict policy; the negative-control fixture demonstrates that
ordinary JavaScript mentions stay clean.

Out of scope for this amendment (documented detection surfaces elsewhere):
browser-svc's duplicate detector and mcp-svc's scrape tool.

## Links

* Supersedes the implicit barrier detection previously spread across `_looks_suspicious()`, `_is_bot_challenge()`, and `smart_scrape()`
* Defined by `scraper-svc/scraper/fetch.py` (`BarrierInfo`, `_classify_barrier`)
* See GitHub issues #51 (barrier detection), #99 (adaptive barrier handling), and #586 (Fastly JS-challenge pages returned as article content)
* Phase 2 will add per-barrier-type retry strategies and configurable confidence thresholds
