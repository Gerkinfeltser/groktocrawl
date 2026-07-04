# MCP Protocol Research: Building an MCP Server in Python

**Date:** 2026-07-03
**Purpose:** Research for Phase 5 — building an MCP server that exposes GroktoCrawl tools

---

## 1. MCP Protocol Specification

### Current Spec Versions

| Version | Status | Key Characteristics |
|---------|--------|---------------------|
| **2025-11-25** | **Stable (current production)** | Stateful sessions, `initialize` handshake, `Mcp-Session-Id` header |
| **2026-07-28** | Release Candidate (locks July 28, 2026) | **Stateless core**, no sessions, no handshake, extensions framework |

### Protocol Architecture (2025-11-25)

- **Base protocol**: JSON-RPC 2.0 over UTF-8
- **Stateful connections** with capability negotiation
- **Server features**: Tools, Resources, Prompts
- **Client features**: Sampling, Roots, Elicitation
- **Utilities**: Configuration, progress tracking, cancellation, error reporting, logging

### Transports (2025-11-25)

| Transport | Use Case | Status |
|-----------|----------|--------|
| **stdio** | Local subprocess communication | Standard (clients SHOULD support) |
| **Streamable HTTP** | Remote servers, multi-client | **Recommended for remote** |
| SSE (HTTP+SSE) | Legacy remote | **Deprecated** since 2025-03-26 |

#### Streamable HTTP Details

- Single endpoint (e.g., `https://example.com/mcp`) supports both GET and POST
- POST: client sends JSON-RPC messages
- GET: optional SSE stream for server-to-client notifications
- Server returns either `Content-Type: application/json` (single response) or `text/event-stream` (SSE stream)
- Session management via `MCP-Session-Id` header (cryptographically secure, ASCII-printable)
- Protocol version negotiation via `MCP-Protocol-Version` header
- Resumability via `Last-Event-ID` header
- **Security**: Validate `Origin` header, bind to localhost for local dev

#### Transport Recommendation for GroktoCrawl

**Streamable HTTP is the clear choice.** Since GroktoCrawl exposes HTTP API endpoints, an MCP server that wraps them should also run as an HTTP service. Streamable HTTP:
- Allows multiple concurrent clients
- Supports streaming for long-running operations (crawls, deep research)
- Works with standard HTTP infrastructure (load balancers, auth middleware)
- Is the forward path — SSE is deprecated

### 2026-07-28 Major Changes

The upcoming spec release (July 28, 2026) is a **breaking change** from 2025-11-25:

1. **Stateless core**: No `initialize`/`initialized` handshake, no `Mcp-Session-Id`. Every request is self-contained.
2. **Header-based routing**: `Mcp-Method` and `Mcp-Name` headers required on Streamable HTTP for gateway routing.
3. **Capability discovery**: `server/discover` method replaces initialize-based negotiation.
4. **Multi Round-Trip**: Server returns `InputRequiredResult` instead of holding SSE streams open for elicitation.
5. **Full JSON Schema 2020-12**: `inputSchema` supports `oneOf`/`anyOf`/`allOf`/`$ref`/`$defs`. `outputSchema` unrestricted.
6. **Caching**: `ttlMs` and `cacheScope` on list/read results.
7. **Extensions framework**: First-class with reverse-DNS IDs, independent versioning. Official extensions: MCP Apps, Tasks.
8. **Deprecated**: Roots, Sampling, Logging (annotation-only, still work for 12 months).

**Recommendation**: Build against **2025-11-25** (stable v1.x SDK) for production. The 2026-07-28 spec and SDK v2 are pre-release and may have breaking changes before July 28. The v1.x SDK continues to receive critical fixes and security patches.

---

## 2. Python Libraries for Building MCP Servers

### Library Comparison

| Library | Version | Package | License | Stars | Maintainer | Status |
|---------|---------|---------|---------|-------|------------|--------|
| **`mcp` (official SDK)** | 1.28.1 stable | `pip install mcp[cli]` | MIT | 23.5k | Anthropic | Production |
| **`mcp` (official SDK v2)** | 2.0.0b1 beta | `pip install mcp==2.0.0b1` | MIT | same repo | Anthropic | Pre-release |
| **FastMCP (built-in)** | bundled in `mcp` v1.x | `from mcp.server.fastmcp import FastMCP` | MIT | — | Anthropic | Stable |
| **FastMCP (standalone)** | 3.4.2 | `pip install fastmcp` | Apache 2.0 | 25.9k | Prefect | Active |

### Detailed Analysis

#### A. `mcp` — Official Python SDK (v1.28.1 stable)

- **Package**: `pip install "mcp[cli]"`
- **Repo**: https://github.com/modelcontextprotocol/python-sdk
- **Protocol**: Implements 2025-11-25 spec
- **Transports**: stdio, Streamable HTTP, SSE (legacy)
- **Python**: 3.10+
- **Key modules**:
  - `mcp.server.fastmcp.FastMCP` — High-level server builder
  - `mcp.server.Server` — Low-level server
  - `mcp.client.Client` — Client for connecting to MCP servers
  - `mcp.types` — Type definitions (Tool, TextContent, etc.)

**Minimum working server (v1.x FastMCP):**

```python
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("GroktoCrawl")

@mcp.tool()
def scrape(url: str, formats: list[str] | None = None) -> str:
    """Scrape a URL and return markdown content."""
    # Call GroktoCrawl scraper
    return "..."

if __name__ == "__main__":
    mcp.run(transport="streamable-http")
```

**Key v1.x FastMCP features:**
- `@mcp.tool()` decorator — auto-generates JSON Schema from type hints
- `@mcp.resource("uri://{param}")` — templated resources
- `@mcp.prompt()` — reusable prompt templates
- `mcp.run(transport="streamable-http")` — runs uvicorn with single `/mcp` endpoint
- `json_response=True` — enables structured JSON output
- Session management handled automatically via `MCP-Session-Id` header
- Built-in MCP Inspector support: `uv run mcp dev server.py`

#### B. FastMCP Standalone (v3.4.2, by Prefect)

- **Package**: `pip install fastmcp`
- **Repo**: https://github.com/PrefectHQ/fastmcp
- **Docs**: https://gofastmcp.com
- **History**: Original FastMCP was incorporated into the official SDK. The standalone version continued independent development with more features.
- **Advantages over built-in FastMCP**:
  - More actively developed (25.9k stars)
  - Additional features: Apps (interactive UIs), client SDK, middleware, providers, transforms
  - Better docs site
  - Component visibility (tag-based filtering, enable/disable)
  - Output schemas, structured outputs
  - Lifespan management
  - Tool annotations (readOnlyHint, destructiveHint, idempotentHint)
  - Dependency injection (`Depends()`)
  - Pagination support
  - Background tasks
  - Session state store

**Minimum working server (standalone FastMCP):**

```python
from fastmcp import FastMCP

mcp = FastMCP("GroktoCrawl")

@mcp.tool
def scrape(url: str, formats: list[str] | None = None) -> str:
    """Scrape a URL and return markdown content."""
    return "..."

if __name__ == "__main__":
    mcp.run(transport="http", host="127.0.0.1", port=9000)
```

**Key differences from built-in FastMCP:**
- Transport parameter: `"http"` instead of `"streamable-http"`
- More tool decorator options: `name`, `description`, `tags`, `annotations`, `output_schema`, `timeout`, `version`
- Server options: `instructions`, `website_url`, `icons`, `auth`, `middleware`, `providers`, `lifespan`, `on_duplicate`

#### C. `mcp` v2.0.0b1 (Beta SDK for 2026-07-28 spec)

- **Package**: `pip install "mcp[cli]==2.0.0b1"`
- **Breaking changes from v1.x**:
  - `MCPServer` replaces `FastMCP` as the high-level API
  - No more `initialize` handshake — no `MCPServer.run()`
  - Client info travels in `_meta` on every request
  - `Client(mcp)` for in-memory testing
  - Tool responses use `result.structured_content` instead of raw content blocks
  - Full JSON Schema 2020-12 support

**Minimum working server (v2 SDK):**

```python
from mcp.server import MCPServer

mcp = MCPServer("Demo")

@mcp.tool()
def add(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b
```

**Recommendation**: Do NOT use v2 for production yet. Wait for stable release (targeted July 27, 2026). Build against v1.x stable.

---

## 3. Tool Definition and JSON Schema

### MCP Protocol Tool Format

Tools are defined with this structure:

```json
{
  "name": "tool_name",
  "title": "Human-Readable Name",
  "description": "What the tool does",
  "inputSchema": {
    "type": "object",
    "properties": {
      "param1": { "type": "string", "description": "..." },
      "param2": { "type": "integer", "description": "..." }
    },
    "required": ["param1"]
  },
  "outputSchema": { "type": "object", "properties": { ... } },
  "annotations": {
    "title": "Display Name",
    "readOnlyHint": true,
    "destructiveHint": false,
    "idempotentHint": true,
    "openWorldHint": true
  }
}
```

### Tool Call Request/Response

**Request** (`tools/call`):
```json
{
  "jsonrpc": "2.0",
  "id": 2,
  "method": "tools/call",
  "params": {
    "name": "tool_name",
    "arguments": { "param1": "value" }
  }
}
```

**Response** — content blocks (one or more):
```json
{
  "jsonrpc": "2.0",
  "id": 2,
  "result": {
    "content": [
      { "type": "text", "text": "Result text" }
    ],
    "structuredContent": { "key": "value" },
    "isError": false
  }
}
```

**Content block types:**
- `{"type": "text", "text": "..."}` — plain text
- `{"type": "image", "data": "<base64>", "mimeType": "image/png"}` — images
- `{"type": "audio", "data": "<base64>", "mimeType": "audio/wav"}` — audio
- `{"type": "resource_link", "uri": "...", "name": "...", "mimeType": "..."}` — resource links
- `{"type": "resource", "resource": {...}}` — embedded resources

**Structured content**: The `structuredContent` field carries JSON data alongside content blocks. For backwards compatibility, servers SHOULD also include serialized JSON in a `TextContent` block.

**Error responses** — two mechanisms:
1. **Protocol errors**: Standard JSON-RPC errors (`{"error": {"code": -32602, "message": "Unknown tool"}}`)
2. **Tool execution errors**: `{"result": {"content": [...], "isError": true}}`

### FastMCP: JSON Schema from Type Hints

Both built-in and standalone FastMCP auto-generate JSON Schema from Python type hints:

```python
@mcp.tool()
def search(
    query: str,                          # required string
    limit: int = 10,                     # optional integer with default
    sources: list[str] | None = None,    # optional list of strings
    format: Literal["markdown", "html"] = "markdown"  # enum constraint
) -> dict:
    """Search and return results."""
    pass
```

This auto-generates:
```json
{
  "type": "object",
  "properties": {
    "query": {"type": "string"},
    "limit": {"type": "integer", "default": 10},
    "sources": {"type": "array", "items": {"type": "string"}},
    "format": {"type": "string", "enum": ["markdown", "html"], "default": "markdown"}
  },
  "required": ["query"]
}
```

**Supported types**: `str`, `int`, `float`, `bool`, `bytes`, `datetime`, `date`, `timedelta`, `list[T]`, `dict[K,V]`, `set[T]`, `T | None`, `Literal`, `Enum`, `Path`, `UUID`, Pydantic models, dataclasses.

**Advanced parameter metadata** (standalone FastMCP):
```python
from typing import Annotated
from pydantic import Field

@mcp.tool
def search(
    query: Annotated[str, Field(description="Search query", min_length=1)],
    limit: Annotated[int, Field(description="Max results", ge=1, le=100)] = 10
) -> dict:
    pass
```

### Output Schemas (standalone FastMCP)

```python
@mcp.tool(output_schema={
    "type": "object",
    "properties": {
        "results": {"type": "array"},
        "total": {"type": "integer"}
    }
})
def search(query: str) -> dict:
    return {"results": [...], "total": 42}
```

---

## 4. Transport: Streamable HTTP Implementation

### Server-Side (v1.x Built-in FastMCP)

```python
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("GroktoCrawl")

# ... define tools ...

if __name__ == "__main__":
    # Runs uvicorn on 0.0.0.0:8000 with single /mcp endpoint
    mcp.run(transport="streamable-http")
```

This starts a uvicorn server with:
- `POST /mcp` — client sends JSON-RPC messages
- `GET /mcp` — optional SSE stream for server-to-client notifications
- Session management via `MCP-Session-Id` header (automatic)

### Server-Side (Standalone FastMCP)

```python
from fastmcp import FastMCP

mcp = FastMCP("GroktoCrawl")

# ... define tools ...

if __name__ == "__main__":
    mcp.run(transport="http", host="127.0.0.1", port=9000)
```

### ASGI Mounting (for integration with existing FastAPI apps)

**Built-in FastMCP (v1.x):**

```python
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("GroktoCrawl")

# Mount as ASGI app
app = mcp.http_app()  # Returns a Starlette ASGI app

# Or mount into existing FastAPI/Starlette app:
from fastapi import FastAPI
api = FastAPI()
api.mount("/mcp", mcp.http_app())
```

**Standalone FastMCP:**

```python
from fastmcp import FastMCP
mcp = FastMCP("GroktoCrawl")

# Mount into FastAPI:
from fastapi import FastAPI
api = FastAPI()
api.mount("/mcp", mcp.http_app())
```

### Client-Side Connection

```python
from mcp import Client

# Connect via Streamable HTTP
client = Client("http://localhost:8000/mcp")

# Call a tool
result = await client.call_tool("scrape", {"url": "https://example.com"})
```

---

## 5. Session Management

### 2025-11-25 Spec (Current Stable)

- Sessions are **stateful** and **required** for Streamable HTTP
- Server assigns `MCP-Session-Id` in `InitializeResult` response header
- Client must include `MCP-Session-Id` on all subsequent requests
- Session ID must be cryptographically secure (UUID, JWT, or hash)
- Session expires: server returns HTTP 404, client must re-initialize
- Session termination: client sends HTTP DELETE to `/mcp` with `MCP-Session-Id`

**In FastMCP**: Session management is handled automatically. The SDK creates sessions on `initialize`, tracks them, and cleans up on disconnect.

### 2026-07-28 Spec (Upcoming)

- **Sessions are removed**. The protocol becomes stateless.
- No `initialize` handshake. Client info in `_meta` on every request.
- Stateful applications use explicit handles: tool returns a `basket_id`, model passes it back.
- Server-to-client requests only during active request processing (no unsolicited messages).
- Multi Round-Trip: server returns `InputRequiredResult` instead of holding SSE streams.

### Standalone FastMCP: Session State Store

```python
mcp = FastMCP(
    "GroktoCrawl",
    session_state_store=my_persistent_store  # Optional
)
```

---

## 6. Recommendation for GroktoCrawl MCP Server

### Library Choice

**Primary recommendation: `mcp` v1.28.1 (official SDK with built-in FastMCP)**

Rationale:
- Official Anthropic SDK, 23.5k stars, MIT licensed
- Stable/production-ready (v1.28.1, released June 2026)
- Implements 2025-11-25 spec (current stable)
- Built-in FastMCP provides the simplest tool definition API
- All transports supported: stdio, Streamable HTTP, SSE
- `mcp[cli]` extras include dev tools (Inspector, `mcp dev`)
- Backed by Anthropic with security patches and critical fixes

**Alternative: Standalone FastMCP v3.4.2**

Reasons you might choose this instead:
- More features (apps, middleware, providers, transforms, dependency injection)
- Better documentation site (gofastmcp.com)
- More actively developed (25.9k stars)
- Tool annotations for better LLM integration (readOnlyHint, etc.)
- Lifespan management for resource cleanup
- However: Apache 2.0 license, independent maintainer (Prefect), depends on `mcp` SDK internally anyway

### Proposed Tool Surface for GroktoCrawl

Based on GroktoCrawl's API surface, the MCP server should expose these tools:

| Tool Name | Maps To | Inputs |
|-----------|---------|--------|
| `scrape` | `POST /v2/scrape` | `url`, `formats`, `only_main_content`, `wait_for` |
| `crawl` | `POST /v2/crawl` | `url`, `max_pages`, `max_depth`, `include_paths`, `exclude_paths` |
| `map` | `POST /v2/map` | `url`, `search`, `ignore_sitemap` |
| `search` | `POST /v2/search` | `query`, `limit`, `sources`, `categories`, `search_type` |
| `agent` | `POST /v2/agent` | `query`, `max_urls`, `model` |
| `answer` | `POST /v2/answer` | `query`, `num_sources` |
| `get_crawl_status` | `GET /v2/crawl/{job_id}` | `job_id` |
| `cancel_crawl` | `DELETE /v2/crawl/{job_id}` | `job_id` |

### Minimum Server Skeleton

```python
"""GroktoCrawl MCP Server — exposes GroktoCrawl tools via Model Context Protocol."""
import os
import httpx
from mcp.server.fastmcp import FastMCP

GROKTOCRAWL_URL = os.getenv("GROKTOCRAWL_URL", "http://agent-svc:8000")

mcp = FastMCP("GroktoCrawl", json_response=True)

@mcp.tool()
async def scrape(
    url: str,
    formats: list[str] | None = None,
    only_main_content: bool = True,
) -> str:
    """Scrape a URL and return its content as markdown.

    Args:
        url: The URL to scrape.
        formats: Content formats to return (default: ["markdown"]).
        only_main_content: Extract only the main content, filtering navigation/ads.
    """
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{GROKTOCRAWL_URL}/v2/scrape",
            json={"url": url, "formats": formats or ["markdown"],
                  "only_main_content": only_main_content},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("data", {}).get("markdown", "")

@mcp.tool()
async def search(
    query: str,
    limit: int = 5,
    search_type: str = "rich",
) -> dict:
    """Search the web and return results.

    Args:
        query: The search query.
        limit: Maximum number of results (1-20).
        search_type: 'fast' for raw results or 'rich' for enriched results.
    """
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{GROKTOCRAWL_URL}/v2/search",
            json={"query": query, "limit": limit, "search_type": search_type},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()

if __name__ == "__main__":
    mcp.run(transport="streamable-http")
```

### Transport Setup

For the GroktoCrawl MCP server, Streamable HTTP is the natural choice:
- Run as a separate container in docker-compose (`mcp-svc`)
- Expose on a port (e.g., 8001)
- Endpoint: `http://mcp-svc:8001/mcp`
- Internal calls to `agent-svc:8000` for GroktoCrawl API
- Clients connect via `http://localhost:8001/mcp` or `http://mcp-svc:8001/mcp`

### Key Implementation Notes

1. **Tool annotations**: Mark read-only tools (`scrape`, `search`, `map`, `answer`, `get_crawl_status`) with `readOnlyHint=True` so clients skip confirmation prompts.
2. **Error handling**: Use `isError: true` in tool results for operational failures (API errors, timeouts), not protocol errors.
3. **Structured output**: Return dict/Pydantic models for rich data; FastMCP auto-creates `structuredContent`.
4. **Streaming**: For long-running operations (`crawl`, `agent`), consider SSE streaming in the tool response.
5. **Authentication**: Add API key auth if GroktoCrawl requires it. Pass through to the GroktoCrawl API.
6. **Docker integration**: Add `mcp-svc` to `docker-compose.yml` with the `mcp` package installed.

---

## 7. References

- MCP Specification (2025-11-25): https://modelcontextprotocol.io/specification/2025-11-25
- MCP Specification (draft/2026-07-28): https://modelcontextprotocol.io/specification/draft
- Official Python SDK: https://github.com/modelcontextprotocol/python-sdk
- Official SDK Docs (v1.x): https://github.com/modelcontextprotocol/python-sdk/blob/v1.x/README.md
- Standalone FastMCP: https://github.com/PrefectHQ/fastmcp
- Standalone FastMCP Docs: https://gofastmcp.com
- MCP Tools Spec: https://modelcontextprotocol.io/specification/2025-06-18/server/tools
- MCP Transports Spec: https://modelcontextprotocol.io/specification/2025-11-25/basic/transports
- 2026-07-28 RC Blog: https://blog.modelcontextprotocol.io/posts/2026-07-28-release-candidate/
- Why SSE Was Deprecated: https://blog.fka.dev/blog/2025-06-06-why-mcp-deprecated-sse-and-go-with-streamable-http
