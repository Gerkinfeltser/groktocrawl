# llms.txt Description Quality: Sentence-Boundary Extraction + Meta Tag Fallback

## Goal

Improve the quality of descriptions in GroktoCrawl's generated `llms.txt` files. Replace the current hard character-slice heuristic with a fallback chain that produces complete sentences and prioritizes semantic content. This addresses issue #17.

## Current Context

- **Issue #17** filed and analyzed — 5-tier fallback chain proposed
- **Comment on #17** recommends a "3 + 1" approach: sentence-boundary detection on markdown + lightweight raw HTML meta tag extraction, deferring LLM summarization
- **Current code** (`agent-svc/agent/llmstxt.py`), line 96: `description = stripped[:150].strip()` — hard char-slice, no sentence awareness, no meta tag fallback
- **Scraper service** (`scraper-svc/scraper/fetch.py`) returns markdown only — HTML meta tags are discarded before the llmstxt module ever sees them
- **Git remote:** `github.com:groktopus/groktocrawl.git`
- **License:** MIT — open source, public repo

## Proposed Approach

Two independent changes, implementable separately:

### Change A: Sentence-boundary-aware description extraction (Tier 3)

Replace the `[:150]` truncation in `extract_title_and_description()` with a function that:
1. Skips boilerplate lines (nav, cookie, footer signals — `<nav>`, "cookie", "skip to", short lines under 30 chars)
2. Finds the first substantive paragraph
3. Extracts to the next sentence boundary (`. `, `! `, `? `) after a minimum threshold (~100 chars)
4. If no sentence boundary found within 300 chars, falls back to the current `[:250]` behavior

This is a pure Python change — no new endpoints, no new dependencies, no scraper changes. ~30 lines in `llmstxt.py`.

### Change B: Lightweight meta tag extraction endpoint (Tiers 1+2)

Add a new endpoint to the **scraper service** (`scraper-svc/scraper/`) that fetches raw HTML (one GET) and extracts `<title>`, `<meta name="description">`, and `<meta property="og:description">` using BeautifulSoup. No Playwright, no readability, no markdown conversion — single HTTP call + soup parsing.

New scraper endpoint: `POST /scrape/head` or `POST /scrape/meta` — returns `{"title": "...", "description": "...", "og_description": "..."}`.

Then wire it into `llmstxt.py` as a pre-scrape step: before the full markdown scrape, do a cheap HEAD-style fetch for meta tags. If a meta description is found (and is > ~40 chars), use it directly and skip the markdown description extraction.

## Step-by-Step Plan

### Issue A: Sentence-boundary extraction (the easy win)

**Files:** `agent-svc/agent/llmstxt.py`

1. Add a `_extract_description(text: str) -> str` helper function:
   - Split text into lines
   - Filter out boilerplate signals: lines under 30 chars, lines containing "cookie", "skip to content", "navigation", lines that are nav/footer/header remnants (all-lowercase, all-caps short strings)
   - From the first passing line, collect text until we hit a sentence boundary (`. `, `! `, `? `) after a minimum of ~100 chars
   - If no boundary found within 300 chars, return `text[:250].rstrip()` + `"..."` if truncated
   - If the resulting description is under 40 chars, continue scanning

2. Replace line 96:
   ```python
   # Old:
   description = stripped[:150].strip()
   # New:
   if not description:
       description = _extract_description(md)
   ```

3. Validate edge cases:
   - Very short pages (no sentence boundary found)
   - Pages with only boilerplate before content
   - Multi-sentence descriptions where only the first sentence is relevant
   - Pages with lists first (bullet points that are actually content)

### Issue B: Lightweight meta tag endpoint + wiring

**Files:** `scraper-svc/scraper/api.py`, `scraper-svc/scraper/fetch.py` (or new `meta.py`), `agent-svc/agent/llmstxt.py`

1. Add `fetch_meta_tags(url: str) -> dict` to the scraper service:
   - Single GET request to the URL
   - Parse with BeautifulSoup (already a dependency)
   - Extract: `title` from `<title>`, `description` from `<meta name="description">`, `og_description` from `<meta property="og:description">`
   - Return `{"title": "...", "description": "...", "og_description": "..."}` with `None` for missing fields

2. Add route `POST /scrape/meta` in the scraper API that calls the above

3. In `llmstxt.py`'s `extract_title_and_description()`:
   - Before the existing scrape call, make a lightweight HTTP call to the new meta endpoint
   - If `description` or `og_description` is found and >= ~40 chars, use it as the description
   - If not, fall through to the existing markdown scrape + sentence-boundary extraction

4. Wire the `scraper_meta_url` through the existing infrastructure (app state, env var or derived from `scraper_url`)

### Issue C: Tests

**Files:** `tests/test_stack.py`

1. `test_llmstxt_description_sentence_boundary()` — Create a test page with multiple sentences, verify description doesn't truncate mid-sentence
2. `test_llmstxt_meta_tag_preference()` — Create a test page with `<meta name="description">`, verify it's preferred over body text
3. `test_llmstxt_fallback_chain()` — Create a test page with no meta tags, verify sentence-boundary extraction works
4. `test_llmstxt_boilerplate_skipping()` — Create a page with nav/cookie banner before content, verify description skips boilerplate

## Issue Filing Strategy

Single coordination issue already exists: **#17**. 
No sub-issues needed — the changes are small enough to track as a single PR.

## PR Strategy

**Two commits on a single branch from main:**

```
feat(llmstxt): add sentence-boundary-aware description extraction
feat(scraper): add /scrape/meta endpoint for raw HTML meta tag extraction
```

Or, if preferred, a single commit:

```
feat(llmstxt): improve description quality with meta tag + sentence-boundary fallback chain
```

## Validation

| Check | Method |
|-------|--------|
| Sentence-boundary correctness | Unit test with known multi-sentence input |
| Meta tag preference | Integration test with test-site fixture page containing `<meta>` tags |
| Boilerplate skipping | Integration test with nav/cookie content before main content |
| Existing llms.txt generation | Verify `generate-llmstxt` endpoint still returns valid output |
| All existing tests | `python3 tests/test_stack.py` — no regressions |

## Risks & Trade-offs

- **Meta tag quality varies:** Some sites have generic `<meta name="description">` like "Welcome to our website" — the 40-char minimum threshold filters these, but some may still slip through. Mitigation: the sentence-boundary extraction on actual page content is still the fallback.
- **Additional HTTP call per page:** The meta endpoint adds one GET per page before the full scrape. This is a tiny cost (meta tags are in the `<head>`, typically <5KB response) compared to the full scrape which may involve Playwright rendering.
- **No LLM tier:** As discussed in the issue comment, LLM summarization is deferred. The heuristic chain covers the vast majority of cases. If deployed and meta + sentence-boundary still produce poor descriptions for certain sites, LLM tier can be added later.
