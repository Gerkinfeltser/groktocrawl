# MCP Server Architecture

* Status: proposed
* Deciders: magnus
* Date: 2026-07-03

Technical Story: AI coding assistants and agent frameworks increasingly use the Model Context
Protocol (MCP) to discover and invoke tools. GroktoCrawl should expose all its capabilities
(scrape, search, crawl, agent, answer, map, extract, sessions) as MCP tools so that coding
agents can use them natively without custom HTTP wrappers.

## Context and Problem Statement

GroktoCrawl exposes a rich HTTP API (30+ endpoints across scrape, search, crawl, agent, answer,
map, extract, monitor, parse, browser, sessions) but AI coding assistants (Claude Code, Cursor,
Windsurf, etc.) communicate with tools via MCP — not raw HTTP. Without an MCP server:

1. **Every integration requires custom code.** Each agent framework needs a custom HTTP client,
   error handling, and parameter mapping for each GroktoCrawl endpoint.

2. **Tool discovery is manual.** Agents can't ask "what can GroktoCrawl do?" — integrators
   must read API docs and hardcode tool definitions.

3. **No standard session management.** MCP provides stateful sessions with abort, progress
   tracking, and logging — building this from scratch for each integration is redundant.

4. **Streaming is ad-hoc.** GroktoCrawl supports SSE streaming but each agent framework
   implements SSE parsing differently. MCP's Streamable HTTP provides a standard mechanism.

The solution is an MCP server that wraps the GroktoCrawl API as a standard set of MCP tools,
runs as a separate Docker service, and supports the MCP 2025-11-25 protocol spec.

## Decision Drivers

* Must expose all GroktoCrawl capabilities as MCP tools with proper JSON Schema inputs
* Must use Streamable HTTP transport (SSE is deprecated as of 2025-03-26)
* Must be a separate service (clean separation, independent scaling, no agent-svc changes)
* Must handle streaming responses (crawl, agent) via MCP's content block mechanism
* Must support authentication (API key passthrough to agent-svc)
* Must use the official `mcp` Python SDK (already installed in the environment, v1.27.0)
* Must not require new Python dependencies beyond `mcp` (per mission constraints)
* Must work within the existing Docker Compose deployment model

## Considered Options

### Option A: ASGI Sub-Application in agent-svc

Mount the MCP server as a FastAPI sub-application within the existing agent-svc process.

**Pros:**
- No separate service — simpler deployment
- Shared process means direct function calls instead of HTTP
- No additional Docker image to build

**Cons:**
- Tight coupling — MCP protocol changes require agent-svc rebuild
- Port sharing complicates rate limiting and health checks
- MCP sessions share memory with API request processing
- Can't scale MCP independently from agent-svc
- Violates separation of concerns — agent-svc becomes a multi-protocol server

### Option B: Separate mcp-svc Docker Service (Chosen)

A standalone Docker service running the official `mcp` Python SDK, communicating with
agent-svc via its internal HTTP API.

**Pros:**
- Clean separation — MCP is a protocol adapter, not part of the core API
- Independent scaling — can run multiple mcp-svc instances behind a load balancer
- agent-svc stays focused on its core API
- MCP server can be tested independently (mocked agent-svc for unit tests)
- Can evolve MCP protocol independently (upgrade SDK without touching agent-svc)
- Follows the existing pattern: `scraper-svc`, `browser-svc`, `semantic-svc` are all separate
  services that communicate via HTTP

**Cons:**
- Additional Docker service to build, deploy, and monitor
- Added latency: MCP → HTTP → agent-svc → HTTP → MCP (estimated +5-15ms per call)
- Need to manage API key passthrough and error propagation across services
- Session state in MCP must correlate with session state in agent-svc

### Option C: Standalone CLI (stdio transport)

An MCP server that runs via stdio, started by the MCP client as a subprocess.

**Pros:**
- Simplest deployment — no port management, no HTTP
- Works out of the box with local MCP clients (Claude Desktop, etc.)

**Cons:**
- No multi-client support — one process per connection
- Doesn't work with remote agents (can't connect over network)
- Requires Python environment on the client machine
- Not compatible with Docker-based agent-svc (would need to run locally with all dependencies)

## Decision Outcome

Chosen option: **Option B — Separate mcp-svc Docker Service**

### Architecture

```
                                    ┌─────────────────┐
 AI Coding Assistant                │   mcp-svc       │       ┌──────────────┐
 (Claude Code, etc.)                │   (Python)       │       │  agent-svc   │
        │                           │                  │       │  (FastAPI)   │
        │ MCP (Streamable HTTP)     │  mcp_server.py   │ HTTP  │              │
        ├──────────────────────────►│  FastMCP         ├──────►│  /v2/scrape  │
        │   POST /mcp               │                  │       │  /v2/search  │
        │   tools/list              │  groktocrawl_    │       │  /v2/crawl   │
        │   tools/call              │  client.py       │       │  /v2/agent   │
        │                           │                  │       │  /v2/answer  │
        │                           │  session_store.py│       │  /v2/session │
        │                           │  (generic TTL    │       │  ...         │
        │                           │   session store) │       └──────────────┘
        │                           └─────────────────┘
```

### File Structure

```
mcp-svc/
├── mcp_server.py           # FastMCP app, tool definitions, server entrypoint
├── groktocrawl_client.py   # HTTP client wrapping agent-svc API
├── session_store.py        # Generic SessionStore (TTL, create/get/execute/destroy)
├── Dockerfile              # Container build
├── pyproject.toml          # Python package metadata
├── requirements.txt        # Pinned dependencies (mcp, httpx, pydantic)
└── tests/
    ├── test_tools.py       # Verify all tools are registered with correct schemas
    ├── test_client.py      # Test groktocrawl_client with mocked agent-svc
    └── test_integration.py # End-to-end with real agent-svc
```

### Component: `mcp_server.py`

Uses the official `mcp` Python SDK's `FastMCP`:

```python
from mcp.server.fastmcp import FastMCP
from groktocrawl_client import GroktoCrawlClient

mcp = FastMCP("GroktoCrawl", json_response=True)
client = GroktoCrawlClient(base_url=..., api_key=...)

@mcp.tool()
async def scrape(url: str, formats: list[str] | None = None,
                 only_main_content: bool = True) -> str:
    """Scrape a URL and return its content as markdown."""
    return await client.scrape(url, formats, only_main_content)

# ... tools for search, crawl, map, agent, answer, extract, session_*, browser_*

if __name__ == "__main__":
    mcp.run(transport="streamable-http")
```

### Component: `groktocrawl_client.py`

A thin HTTP client that wraps the agent-svc API with proper error handling:

```python
class GroktoCrawlClient:
    def __init__(self, base_url: str, api_key: str | None = None)

    # Core tools
    async def scrape(self, url: str, ...) -> dict
    async def search(self, query: str, ...) -> dict
    async def crawl(self, url: str, ...) -> dict
    async def map(self, url: str, ...) -> dict

    # Agent tools
    async def agent(self, prompt: str, ...) -> dict
    async def answer(self, query: str, ...) -> dict
    async def extract(self, urls: list[str], prompt: str, ...) -> dict

    # Session tools (Phase 2+)
    async def session_create(self) -> dict
    async def session_step(self, session_id: str, action: str, params: dict) -> dict
    async def session_get(self, session_id: str) -> dict
    async def session_export(self, session_id: str) -> str
    async def session_delete(self, session_id: str) -> bool

    # Research memory tools (Phase 4+)
    async def research_memory_query(self, query: str) -> dict | None
    async def research_memory_store(self, query: str, artifact: str) -> str
```

### Component: `session_store.py`

A generic session store for MCP's stateful session management. Supports both the MCP
protocol's own session state AND user-facing GroktoCrawl research sessions (when Phase 2
lands). In the initial Phase 5 deployment, it manages MCP protocol sessions only.

```python
class SessionStore:
    """Generic in-memory session store with TTL and sweep."""

    def __init__(self, ttl: int = 3600, sweep_interval: int = 300)

    def create(self, metadata: dict | None = None) -> str
    def get(self, session_id: str) -> dict | None
    def update(self, session_id: str, data: dict) -> None
    def destroy(self, session_id: str) -> None
    def sweep(self) -> int
```

### Docker Configuration

```yaml
# docker-compose.yml addition
mcp-svc:
  build:
    context: ./mcp-svc
  ports:
    - "${MCP_PORT:-8002}:8002"
  environment:
    - GROKTOCRAWL_URL=http://agent-svc:8000
    - GROKTOCRAWL_API_KEY=${API_KEY:-}
    - MCP_PORT=8002
    - SESSION_TTL=${MCP_SESSION_TTL:-3600}
  depends_on:
    - agent-svc
  restart: unless-stopped
  profiles:
    - all
    - mcp
```

### MCP Tools Surface (Phase 1 — 17 tools from today's API)

| # | Tool Name | Maps To | Annotations |
|---|-----------|---------|-------------|
| 1 | `scrape` | `POST /v2/scrape` | readOnlyHint=true |
| 2 | `search` | `POST /v2/search` | readOnlyHint=true |
| 3 | `crawl` | `POST /v2/crawl` | destructiveHint=true |
| 4 | `get_crawl_status` | `GET /v2/crawl/{job_id}` | readOnlyHint=true |
| 5 | `cancel_crawl` | `DELETE /v2/crawl/{job_id}` | destructiveHint=true |
| 6 | `get_crawl_errors` | `GET /v2/crawl/{job_id}/errors` | readOnlyHint=true |
| 7 | `map` | `POST /v2/map` | readOnlyHint=true |
| 8 | `agent` | `POST /v2/agent` | readOnlyHint=true |
| 9 | `get_agent_status` | `GET /v2/agent/{job_id}` | readOnlyHint=true |
| 10 | `answer` | `POST /v2/answer` | readOnlyHint=true |
| 11 | `extract` | `POST /v2/extract` | readOnlyHint=true |
| 12 | `get_extract_status` | `GET /v2/extract/{job_id}` | readOnlyHint=true |
| 13 | `enrich` | `POST /v2/enrich` | readOnlyHint=true |
| 14 | `find_similar` | `POST /v2/find-similar` | readOnlyHint=true |
| 15 | `batch_scrape` | `POST /v2/batch/scrape` | destructiveHint=true |
| 16 | `generate_llmstxt` | `POST /v2/generate-llmstxt` | destructiveHint=true |
| 17 | `get_activity` | `GET /v2/activity` | readOnlyHint=true |

### MCP Tools Surface (Phase 2 — 8 additional tools as features land)

| # | Tool Name | Maps To | Phase |
|---|-----------|---------|-------|
| 18 | `session_create` | `POST /v2/session/create` | 2 |
| 19 | `session_step` | `POST /v2/session/{id}/step` | 2 |
| 20 | `session_get` | `GET /v2/session/{id}` | 2 |
| 21 | `session_export` | `POST /v2/session/{id}/export` | 2 |
| 22 | `resolve_citations` | `POST /v2/citations/resolve` | 1 |
| 23 | `plan_agent` | `POST /v2/agent {mode:"plan"}` | 3 |
| 24 | `execute_plan` | `POST /v2/agent/execute` | 3 |
| 25 | `research_memory_query` | `POST /v2/research-memory/query` | 4 |

### Authentication

- MCP server reads `GROKTOCRAWL_API_KEY` from environment
- Passes it as `X-API-Key` or `Authorization: Bearer` header on all requests to agent-svc
- If `GROKTOCRAWL_API_KEY` is not set, requests are unauthenticated (works when agent-svc
  has no `API_KEY` configured)
- MCP clients authenticate to the MCP server via standard HTTP mechanisms (API gateway,
  Traefik middleware) — the MCP server itself does not implement MCP-level auth

### Error Propagation

agent-svc errors are propagated as MCP tool execution errors:
```json
{
  "content": [
    {"type": "text", "text": "Scrape failed: upstream timeout after 30s"}
  ],
  "isError": true
}
```

Standard error codes map to structured error content:
- 4xx → tool execution error with validation details
- 5xx → tool execution error with retry hint
- Timeout → tool execution error with timeout duration

## Positive Consequences

* Coding assistants get first-class GroktoCrawl integration with zero custom code
* Tool discovery via `tools/list` eliminates manual API documentation parsing
* FastMCP auto-generates JSON Schema from Python type hints — tool definitions stay in sync
  with implementation
* Streamable HTTP transport supports multi-client concurrency and streaming responses
* Independent scaling: run more mcp-svc instances for high-traffic agent workloads
* Generic SessionStore design supports both MCP sessions and future GroktoCrawl research
  sessions with the same abstraction
* Follows the existing architectural pattern of separate services communicating via HTTP

## Negative Consequences

* Additional HTTP hop adds ~5-15ms latency per tool call
* Two services to monitor and debug (mcp-svc + agent-svc)
* MCP protocol versioning risk — 2026-07-28 spec is a breaking change from 2025-11-25.
  Mitigation: build against stable v1.x SDK, monitor v2.x development
* Tool definitions must stay synchronized with agent-svc API changes. Mitigation: integration
  tests verify tool signatures against the actual agent-svc API
* No built-in MCP-level auth — relies on external API gateway for client authentication
* GroktoCrawl API calls that return job IDs (crawl, agent, extract) require the MCP client
  to poll — no MCP-native async result mechanism. Mitigation: these tools return the job ID
  and the client uses `get_*_status` tools

## Links

* Issue [#393: MCP server](https://github.com/groktopus/groktocrawl/issues/393)
* [MCP 2025-11-25 Specification](https://modelcontextprotocol.io/specification/2025-11-25)
* [Official Python SDK (mcp v1.x)](https://github.com/modelcontextprotocol/python-sdk)
* Related: [ADR-0040: Session Protocol](0040-session-protocol.md)
* Related: [ADR-0041: Research Memory](0041-research-memory.md)
* Precedent in codebase: `browser-svc` wraps browser automation as an HTTP service,
  `scraper-svc` wraps Playwright as an HTTP service — mcp-svc follows the same adapter pattern
