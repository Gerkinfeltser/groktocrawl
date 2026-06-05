# Binary Content Detection and Download

* Status: accepted
* Deciders: magnus, jasper
* Date: 2026-06-05

Technical Story: The scraper pipeline assumed all URLs returned HTML. PDFs, images, EPUBs, and other binary content types would either fail to parse or produce garbled markdown.

## Context and Problem Statement

When the scraper encounters a URL that returns binary content (PDF, image, EPUB, ZIP, etc.), the HTML-to-markdown conversion pipeline produces either empty output or garbage. The client has no way to distinguish "this is a downloadable file" from "scraping failed."

The scrape API response model also had no fields for binary content — it assumed markdown text was always the output.

## Decision Drivers

* Detect binary content types before attempting HTML parsing
* Return structured metadata about the binary file (filename, content_type, size)
* Provide a download subcommand that saves binary content to disk
* Support both content-type detection and URL extension heuristics

## Considered Options

* **A. Content-Type detection in fetch pipeline** — Check `Content-Type` header in Tier 2 (content negotiation). If binary, short-circuit to download payload.
* **B. Extension-based detection only** — Check URL extension (.pdf, .epub, etc.). Faster but misses misconfigured servers.
* **C. Hybrid — Content-Type + extension heuristic** — Check Content-Type first, fall back to extension analysis for embed/iframe content.

## Decision Outcome

Chosen option: **C. Hybrid approach**. Tier 2 checks `Content-Type` header first. A `_is_binary_content_type()` function classifies known binary MIME types. For embedded content (iframes pointing to PDFs), a separate `_has_embedded_content()` function inspects the HTML for document-serving domains and file extensions.

The scrape response model gained an optional `download` field:
```json
{
  "markdown": "",
  "download": {
    "filename": "report.pdf",
    "content_type": "application/pdf",
    "size": 123456
  }
}
```

### Positive Consequences

* Binary content is properly detected and returned with metadata
* CLI `download` subcommand can save binary files by filename
* Embedded content detection handles iframe-based document portals (sci-hub, docdrop, arxiv)

### Negative Consequences

* Content-Type headers can be misleading (generic `application/octet-stream`). Extension heuristics mitigate this.
* Embedded content detection adds a lightweight HTML scan to the pipeline (negligible cost)

## Links

* Implemented by PR #35 (content-type detection), #34 (download subcommand), #31 (response model), #26 (binary detection), #25 (download), #24 (stealth browser fixes)
* Defined by `scraper-svc/scraper/fetch.py` (`_is_binary_content_type`, `_has_embedded_content`, `_make_download_payload`)
