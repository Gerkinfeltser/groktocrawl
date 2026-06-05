# Extraction Quality Gates — Post-Extraction Content Quality Assessment

* Status: accepted
* Deciders: magnus, jasper
* Date: 2026-06-05

Technical Story: The scraper returns whatever markdown it produces with no content quality assessment. Block pages, boilerplate-only content, empty bodies, and incomplete extractions all look like successful scrapes to the caller. This is the most common failure mode in web scraping — and currently invisible.

## Context and Problem Statement

The existing barrier classification (ADR-0015) detects *pre-extraction* barriers — pages that are themselves challenge walls, captchas, or error responses. However, many failure modes pass the barrier check but produce useless content:

1. **Boilerplate-heavy pages** — navigation menus, link lists, cookie consent walls, and footer content rendered as "article text"
2. **Incomplete extractions** — readability may return only a title and first paragraph for JS-rendered pages that didn't fully load
3. **Block pages that rendered as text** — Cloudflare challenge text that wasn't caught by pattern matching but made it through as garbled markdown
4. **Geo-block messages** — "This content is not available in your country" rendered as the page body
5. **Members-only previews** — signup walls that render as short snippets

These failures are post-extraction — they happen *after* readability/markdownify conversion. The extraction pipeline cannot detect its own failures.

## Decision Drivers

* Gates must run after markdown conversion — not before or during
* Quality score must be non-blocking — consumers decide their own tolerance
* Must be lightweight — no external APIs, no LLM calls for basic assessment
* Must complement existing barrier classification (ADR-0015), not duplicate it
* Quality score must be exposed in both scraper-svc and agent-svc response models
* Default thresholds must work without configuration but be overridable

## Considered Options

* **A. Lightweight heuristic gates in extract.py** — Pattern matching, content ratio analysis, and structure checks. No external dependencies. Returns score and structured breakdown.
* **B. LLM-based quality assessment** — Use the agent's LLM to rate content quality. More accurate but expensive and introduces latency.
* **C. Headless browser screenshot comparison** — Compare rendered page screenshot metadata against content to detect mismatches. High overhead, complex.
* **D. No quality gates** — Rely entirely on pre-extraction barrier detection. Current state — misses the entire class of post-extraction failures.

## Decision Outcome

Chosen option: **A. Lightweight heuristic gates in extract.py**. Three independent quality gates that run after readability/markdownify conversion, producing a composite quality score (0.0–1.0) with structured breakdown.

### Quality Gates

#### 1. Boilerplate Detection

Detects content that is mostly navigation, menus, links, or templates rather than substantive article text.

**Signals:**
- Link-to-content ratio — markdown link density
- Paragraph quality — proportion of non-link, multi-sentence paragraphs
- Content length after link removal

**Scoring:**
- >70% link lines with <3 substantive paragraphs → `fail` (nav/listing page)
- >50% link lines with <2 substantive paragraphs → `warn`
- 5+ substantive paragraphs → `pass`

#### 2. Completeness Check

Verifies the extracted content meets minimum quality thresholds.

**Signals:**
- Total content length (min 200 chars)
- Title quality (min 10 chars, where available)
- Paragraph structure (min 2 paragraphs)
- Content depth (>1000 chars with paragraphs → full confidence)

**Scoring:**
- <200 chars + no paragraphs → `fail`
- <200 chars or no paragraphs → `warn`
- >=1000 chars with paragraphs + quality title → `pass`
- >=500 chars with paragraphs → `pass`

#### 3. Block Page Detection (Post-Extraction)

Detects pages that rendered as text but are actually error pages, consent walls, or geo-blocks.

**Pattern sets:**
- JavaScript requirements ("please enable javascript")
- Bot challenges ("we need to make sure you're not a robot")
- Access control ("access denied", "you have been blocked")
- Rate limiting ("too many requests", "rate limit")
- Geo-restriction ("not available in your country/region")
- Paywalls ("subscribe to continue", "members-only")
- Cookie consent walls ("cookies are required", "please accept cookies")
- Error pages (404, 403, timeout, etc.)

**Scoring:**
- 3+ pattern matches → `fail` (high confidence block page)
- 2 pattern matches → `fail` (moderate confidence)
- 1 pattern match → `warn`
- No matches and adequate content → `pass`

#### Composite Quality Score

```
overall = boilerplate_score * 0.3 + completeness_score * 0.3 + block_score * 0.4
```

Weights favor block detection because silent block pages are the most harmful failure mode.

### Integration

```
extract.py (new):
  QualityGateResult dataclass
  assess_quality(markdown, html="", url="", title="") → dict
    ├── _check_boilerplate(markdown) → (score, status)
    ├── _check_completeness(markdown, title) → (score, status)
    └── _check_block_page(markdown, url) → (score, status)

fetch.py (modified):
  smart_scrape() calls assess_quality() after each successful tier
  Quality score added to result dict as {"quality": {...}}

app.py (modified):
  ScrapeResponse.data dict includes quality field

agent-svc/models.py (modified):
  ScrapeData accepts quality in metadata
```

### Response Format

```json
{
  "quality": {
    "score": 0.95,
    "checks": {
      "boilerplate": "pass",
      "completeness": "pass",
      "block_detected": "pass"
    },
    "detail": "all checks passed"
  }
}
```

### Default Thresholds

| Parameter | Default | Configurable |
|---|---|---|
| `MIN_CONTENT_CHARS` | 200 | Via env var |
| `MIN_TITLE_CHARS` | 10 | Via env var |
| `MAX_BOILERPLATE_RATIO` | 0.7 | Via env var |

### Positive Consequences

* Catches the most common silent failure mode in web scraping — content that looks successful but is useless
* Works across all extraction tiers (llms.txt, content-negotiation, Playwright, FlareSolverr, LLM recovery)
* Lightweight — no external calls, no LLM tokens for basic assessment
* Non-blocking — consumers choose their tolerance threshold
* Groundwork for future graceful degradation (re-fetch on low quality)

### Negative Consequences

* Heuristic gates can produce false positives (legitimate content flagged as low quality) and false negatives (bad content passing all gates)
* Pattern-based block page detection is English-centric — may miss non-English block pages
* Block page detection partially overlaps with existing barrier classification — overlap is intentional (catches barriers that pattern-matching missed) but adds code surface

## Links

* Supersedes the empty `extract.py` stub
* Complements [ADR-0015: Barrier Classification Phase 1](0015-barrier-classification.md) (pre-extraction barrier detection)
* Phase 2 will add graceful degradation — re-fetch via next tier when quality is below threshold
