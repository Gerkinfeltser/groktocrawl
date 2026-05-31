     1|# GroktoCrawl CLI examples
     2|
     3|## Scrape
     4|
     5|```bash
     6|# Basic scrape to stdout
     7|scripts/groktocrawl scrape https://example.com
     8|
     9|# JSON output (markdown in response)
    10|scripts/groktocrawl scrape https://example.com --json
    11|
    12|# Save to file
    13|scripts/groktocrawl scrape https://example.com -o page.md
    14|
    15|# Custom timeout
    16|scripts/groktocrawl scrape https://heavy-site.com --timeout 120000
    17|```
    18|
    19|## Search
    20|
    21|```bash
    22|# Basic search
    23|scripts/groktocrawl search "raspberry pi 5" --limit 5
    24|
    25|# Search with scraped results (also fetches page content)
    26|scripts/groktocrawl search "latest AI news" --limit 3 --scrape-results
    27|
    28|# Machine-readable output
    29|scripts/groktocrawl search "python async" --limit 5 --json
    30|```
    31|
    32|## Search-then-scrape workflow
    33|
    34|```bash
    35|# Step 1: Search with JSON output to inspect results
    36|scripts/groktocrawl search "mesh networking" --limit 3 --json
    37|
    38|# Step 2: Scrape a specific result URL from the search output
    39|scripts/groktocrawl scrape https://en.wikipedia.org/wiki/Mesh_networking
    40|
    41|# One-shot version (search + content in one command):
    42|scripts/groktocrawl search "mesh networking" --limit 3 --scrape-results
    43|```
    44|
    45|## Map
    46|
    47|```bash
    48|# Discover all URLs on a site
    49|scripts/groktocrawl map https://docs.example.com --limit 100
    50|
    51|# Filter by search term
    52|scripts/groktocrawl map https://example.com --search "blog" --limit 50
    53|```
    54|
    55|## Crawl
    56|
    57|```bash
    58|# Crawl with polling (default — waits for completion)
    59|scripts/groktocrawl crawl https://docs.example.com --max-depth 2 --limit 30
    60|
    61|# Crawl without polling (just returns job ID)
    62|scripts/groktocrawl crawl https://blog.example.com --no-poll
    63|
    64|# Crawl with path filters
    65|scripts/groktocrawl crawl https://example.com --include-paths /blog/* /docs/*
    66|```
    67|
    68|## Agent (research)
    69|
    70|```bash
    71|# Autonomous research — searches, scrapes, synthesizes
    72|scripts/groktocrawl agent "What were the key announcements from Google I/O 2025?"
    73|
    74|# Research with seed URLs (skip search step)
    75|scripts/groktocrawl agent "Compare pricing" --urls https://page1.com https://page2.com
    76|
    77|# Just get the job ID without waiting
    78|scripts/groktocrawl agent "Research topic" --no-poll --json
    79|```
    80|
    81|## Extract
    82|
    83|```bash
    84|# Extract data from URLs with a prompt
    85|scripts/groktocrawl extract https://example.com/pricing --prompt "Find all pricing plans"
    86|
    87|# JSON output
    88|scripts/groktocrawl extract https://page1.com https://page2.com --prompt "Extract names" --json
    89|```
    90|
    91|## Browser
    92|
    93|```bash
    94|# Create a session
    95|SESSION=$(scripts/groktocrawl browser create --ttl 300 --json | python3 -c "import sys,json; print(json.load(sys.stdin)['session_id'])")
    96|
    97|# Navigate to a URL
    98|scripts/groktocrawl browser exec "$SESSION" navigate --url https://example.com
    99|
   100|# Click a button
   101|scripts/groktocrawl browser exec "$SESSION" click --selector "#submit"
   102|
   103|# Type into a field
   104|scripts/groktocrawl browser exec "$SESSION" type --selector "#email" --text "user@example.com"
   105|
   106|# Take a screenshot (returns base64)
   107|scripts/groktocrawl browser exec "$SESSION" screenshot --json
   108|
   109|# Get page content
   110|scripts/groktocrawl browser exec "$SESSION" getContent --json
   111|
   112|# Run JavaScript
   113|scripts/groktocrawl browser exec "$SESSION" executeScript --script "document.title"
   114|
   115|# List active sessions
   116|scripts/groktocrawl browser list
   117|
   118|# Destroy session
   119|scripts/groktocrawl browser destroy "$SESSION"
   120|```
   121|
   122|## Active jobs
   123|
   124|```bash
   125|# List active crawl jobs
   126|scripts/groktocrawl active
   127|
   128|# JSON output
   129|scripts/groktocrawl active --json
   130|```
   131|
   132|## Endpoints via curl (no CLI subcommand yet)
   133|
   134|```bash
   135|# Parse a document (PDF, DOCX, etc.)
   136|curl -X POST http://localhost:8080/v2/parse -F "file=@report.pdf"
   137|
   138|# Monitor CRUD
   139|curl -X POST http://localhost:8080/v2/monitor \
   140|  -H "Content-Type: application/json" \
   141|  -d '{"url": "https://example.com/pricing", "schedule": "0 */6 * * *"}'
   142|curl http://localhost:8080/v2/monitor
   143|curl -X PATCH http://localhost:8080/v2/monitor/<id> \
   144|  -H "Content-Type: application/json" \
   145|  -d '{"schedule": "0 */3 * * *"}'
   146|curl -X DELETE http://localhost:8080/v2/monitor/<id>
   147|
   148|# Generate llms.txt
   149|JOB=$(curl -s -X POST http://localhost:8080/v2/generate-llmstxt \
   150|  -H "Content-Type: application/json" \
   151|  -d '{"url": "https://example.com", "max_pages": 50}')
   152|JOB_ID=$(echo "$JOB" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
   153|curl "http://localhost:8080/v2/generate-llmstxt/$JOB_ID"
   154|
   155|# Webhook on any async job
   156|curl -X POST http://localhost:8080/v2/agent \
   157|  -H "Content-Type: application/json" \
   158|  -d '{"prompt": "Research topic", "webhook": {"url": "https://myapp.com/hook", "events": ["completed"]}}'
   159|```
   160|
   161|## Custom server
   162|
   163|```bash
   164|# All commands support --server
   165|scripts/groktocrawl scrape https://example.com --server http://my-groktocrawl:8080
   166|scripts/groktocrawl search "query" --server http://192.168.1.100:8080 --json
   167|```
   168|