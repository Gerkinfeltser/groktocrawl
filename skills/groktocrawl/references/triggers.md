# When to use the groktocrawl skill

## Decision table

| User says… | Use this command | Why |
|------------|-----------------|-----|
| "Scrape this URL" / "Get me the content of this page" | `scripts/groktocrawl scrape <url>` | Single page, no synthesis needed |
| "Search for X" / "Find information about Y" | `scripts/groktocrawl search "<query>"` | Raw results, no cross-source synthesis |
| "Research X" / "Tell me about Y" / "What happened at Z" | `scripts/groktocrawl agent "<prompt>"` | Needs search, scrape, and synthesis |
| "Compare A and B" | `scripts/groktocrawl agent "Compare A and B"` | Multi-source synthesis |
| "Find all URLs on this site" / "Map this site" | `scripts/groktocrawl map <url>` | URL discovery only |
| "Crawl this site" / "Get all pages from this site" | `scripts/groktocrawl crawl <url>` | Full site scrape |
| "Extract data from these URLs" | `scripts/groktocrawl extract <urls...>` | Structured extraction, no search |
| "Open a browser" / "Take a screenshot" / "Click this button" | `scripts/groktocrawl browser create/exec/destroy` | Interactive browser session |
| "Parse this PDF" / "Extract text from this document" | Use `curl -X POST .../v2/parse -F "file=@..."` | Not yet a CLI subcommand |
| "Watch this page for changes" / "Monitor this URL" | Use `curl` to `/v2/monitor` | Not yet a CLI subcommand |
| "Generate llms.txt for this site" | `curl -X POST .../v2/generate-llmstxt` | Not yet a CLI subcommand |

## Rule of thumb

If the answer requires reading 2+ sources and connecting them, use `agent`. If you just need to find content or scrape a single page, use `scrape` or `search`.
