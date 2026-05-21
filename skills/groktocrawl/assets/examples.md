# GroktoCrawl CLI examples

## Scrape

```bash
# Basic scrape to stdout
scripts/groktocrawl scrape https://example.com

# JSON output (markdown in response)
scripts/groktocrawl scrape https://example.com --json

# Save to file
scripts/groktocrawl scrape https://example.com -o page.md

# Custom timeout
scripts/groktocrawl scrape https://heavy-site.com --timeout 120000
```

## Search

```bash
# Basic search
scripts/groktocrawl search "raspberry pi 5" --limit 5

# Search with scraped results (also fetches page content)
scripts/groktocrawl search "latest AI news" --limit 3 --scrape-results

# Machine-readable output
scripts/groktocrawl search "python async" --limit 5 --json
```

## Map

```bash
# Discover all URLs on a site
scripts/groktocrawl map https://docs.example.com --limit 100

# Filter by search term
scripts/groktocrawl map https://example.com --search "blog" --limit 50
```

## Crawl

```bash
# Crawl with polling (default — waits for completion)
scripts/groktocrawl crawl https://docs.example.com --max-depth 2 --limit 30

# Crawl without polling (just returns job ID)
scripts/groktocrawl crawl https://blog.example.com --no-poll

# Crawl with path filters
scripts/groktocrawl crawl https://example.com --include-paths /blog/* /docs/*
```

## Agent (research)

```bash
# Autonomous research — searches, scrapes, synthesizes
scripts/groktocrawl agent "What were the key announcements from Google I/O 2025?"

# Research with seed URLs (skip search step)
scripts/groktocrawl agent "Compare pricing" --urls https://page1.com https://page2.com

# Just get the job ID without waiting
scripts/groktocrawl agent "Research topic" --no-poll --json
```

## Extract

```bash
# Extract data from URLs with a prompt
scripts/groktocrawl extract https://example.com/pricing --prompt "Find all pricing plans"

# JSON output
scripts/groktocrawl extract https://page1.com https://page2.com --prompt "Extract names" --json
```

## Browser

```bash
# Create a session
SESSION=$(scripts/groktocrawl browser create --ttl 300 --json | python3 -c "import sys,json; print(json.load(sys.stdin)['session_id'])")

# Navigate to a URL
scripts/groktocrawl browser exec "$SESSION" navigate --url https://example.com

# Click a button
scripts/groktocrawl browser exec "$SESSION" click --selector "#submit"

# Type into a field
scripts/groktocrawl browser exec "$SESSION" type --selector "#email" --text "user@example.com"

# Take a screenshot (returns base64)
scripts/groktocrawl browser exec "$SESSION" screenshot --json

# Get page content
scripts/groktocrawl browser exec "$SESSION" getContent --json

# Run JavaScript
scripts/groktocrawl browser exec "$SESSION" executeScript --script "document.title"

# List active sessions
scripts/groktocrawl browser list

# Destroy session
scripts/groktocrawl browser destroy "$SESSION"
```

## Active jobs

```bash
# List active crawl jobs
scripts/groktocrawl active

# JSON output
scripts/groktocrawl active --json
```

## Endpoints via curl (no CLI subcommand yet)

```bash
# Parse a document (PDF, DOCX, etc.)
curl -X POST http://localhost:8080/v2/parse -F "file=@report.pdf"

# Monitor CRUD
curl -X POST http://localhost:8080/v2/monitor \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com/pricing", "schedule": "0 */6 * * *"}'
curl http://localhost:8080/v2/monitor
curl -X PATCH http://localhost:8080/v2/monitor/<id> \
  -H "Content-Type: application/json" \
  -d '{"schedule": "0 */3 * * *"}'
curl -X DELETE http://localhost:8080/v2/monitor/<id>

# Generate llms.txt
JOB=$(curl -s -X POST http://localhost:8080/v2/generate-llmstxt \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com", "max_pages": 50}')
JOB_ID=$(echo "$JOB" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
curl "http://localhost:8080/v2/generate-llmstxt/$JOB_ID"

# Webhook on any async job
curl -X POST http://localhost:8080/v2/agent \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Research topic", "webhook": {"url": "https://myapp.com/hook", "events": ["completed"]}}'
```

## Custom server

```bash
# All commands support --server
scripts/groktocrawl scrape https://example.com --server http://my-groktocrawl:8080
scripts/groktocrawl search "query" --server http://192.168.1.100:8080 --json
```
