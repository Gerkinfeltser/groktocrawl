# GroktoCrawl Architecture

## System Context

```mermaid
flowchart LR
    user("User / CLI")
    agent_api("GroktoCrawl Agent API\n[FastAPI] Port 8080")
    scraper_svc("Scraper Service\n[Python] Port 8001")
    browser_svc("Browser Service\n[Playwright] Port 8012")
    valkey("Valkey\n[Key-Value Store]")
    searxng("SearXNG\n[Search Engine]")
    llm_svc("LLM Service\n[OpenAI Compatible]")
    flare_solverr("FlareSolverr\n[Cloudflare Solver]")

    user -->|"CLI / curl / SDK"| agent_api
    agent_api -->|"/v2/scrape"| scraper_svc
    agent_api -->|"/v2/search"| searxng
    agent_api -->|"/v2/agent"| llm_svc
    agent_api <-->|"Job status"| valkey
    scraper_svc --> browser_svc
    scraper_svc --> flare_solverr
    scraper_svc --> llm_svc

    style user fill:#084,color:#fff
    style agent_api fill:#06c,color:#fff
    style scraper_svc fill:#06c,color:#fff
    style browser_svc fill:#06c,color:#fff
    style valkey fill:#963,color:#fff
    style searxng fill:#963,color:#fff
    style llm_svc fill:#639,color:#fff
    style flare_solverr fill:#639,color:#fff
```

## Container Diagram (internal services)

```mermaid
flowchart LR
    subgraph agent_svc["Agent Service (FastAPI)"]
        api_routes["API Routes\napi.py"]
        worker["Async Worker\nworker.py"]
        research["Research Agent\nresearch.py"]
        scraper_client["Scraper Client\nscraper_client.py"]
        searxng_client["SearXNG Client\nsearxng_client.py"]
        webhook["Webhook Deliverer\nwebhook.py"]
    end

    subgraph scraper_svc["Scraper Service (FastAPI)"]
        smart_scrape["Smart Scrape\nfetch.py"]
        tier1["Tier 1: llms.txt"]
        tier2["Tier 2: Content Neg."]
        tier3["Tier 3: Playwright"]
        tier35["Tier 3.5: FlareSolverr"]
        tier4["Tier 4: LLM Recovery"]
        adapters["Adapter Registry\nadapters/"]
        youtube_ad["YouTube Adapter"]
        bluesky_ad["Bluesky Adapter"]
    end

    smart_scrape --> tier1
    tier1 --> tier2
    tier2 --> tier3
    tier3 --> tier35
    tier35 --> tier4
    smart_scrape -.-> adapters
    adapters --> youtube_ad
    adapters --> bluesky_ad

    agent_svc --> scraper_svc
```

## Available Adapters

| Adapter | Source | Fallback Chain | Docs |
|---------|--------|----------------|------|
| YouTube | `adapters/youtube.py` | youtube_transcript_api → browser render | ADR-0001–0009 |
| Bluesky | `adapters/bluesky.py` | AT Protocol API → browser render | ADR-0001–0009 |
