---
name: spa-vs-article-scraping
description: "Diagnostic pattern: when groktocrawl scrape fails on a SPA index page, individual server-rendered article pages may still work. Test one article before committing to browser extraction."
version: 1.0.0
---

# SPA Index vs. Server-Rendered Article Scraping

## The Pattern

When `groktocrawl scrape` fails on a site's index page (React SPA shell, < 100 chars), individual article pages on the same domain may still be server-rendered and scrape successfully. **Always test scrape on one individual article page before committing to browser-based extraction.**

## Diagnostic Workflow

1. Try `groktocrawl scrape <index-page>` — if < 100 chars, index is client-rendered
2. Check for a sitemap: `curl -sL <domain>/sitemap.xml`
3. Test scrape on one article: `groktocrawl scrape <article-url>`
4. If article returns rich markdown (> 500 chars), batch-scrape all articles

## Worked Example: YC Library (June 2026)

- Index: `ycombinator.com/library` → empty (SPA shell)
- Sitemap: `ycombinator.com/library/sitemap.xml` → 464 article URLs
- Article test: `ycombinator.com/library/4D-slug` → full server-rendered markdown
- Batch: 464 articles × ~7s each = ~15 min total extraction
- Savings: ~50+ minutes vs browser-based extraction
