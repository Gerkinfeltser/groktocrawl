# ADR-0033: Search Volume Controls for Agent Service

**Status:** Proposed

**Deciders:** Magnus Hedemark, Jasper (AI Agent)

**Date:** 2026-06-14

## Context

GroktoCrawl agents can reflexively call search 5+ times per user turn via the `answer` and `agent` endpoints. Each search call burns a Brave API query (paid, $5/1K). During heavy research sessions, a single conversation can consume 50+ Brave queries in minutes — the June 9-10 spike burned 3,927 queries in 48 hours, eating 78% of the monthly $25 budget.

The SlopSearX downstream cache alone cannot solve this because most agent queries are long-tail unique. The fix needs to live at the agent-svc level where search volume is initiated.

Currently:
- `/v2/answer` → `run_answer()` creates a `SearXNGClient` and calls `.search()` once per HTTP request
- `/v2/agent` (streaming) → `run_research_stream()` creates a `SearXNGClient` and calls `.search()` once
- `/v2/agent` (async job) → `_process_agent_async()` → `run_research()` → `.search()` once
- `/v2/search` → creates a `SearXNGClient` and calls `.search()` once
- `/v1/search` → creates a `SearXNGClient` and calls `.search()` once

Each user-facing HTTP request currently produces exactly one search call per endpoint function. However, future research loops or recursive agent behavior could multiply this. The controls need to be in place before those patterns arrive.

## Decision Drivers

1. **Zero new infrastructure** — Valkey (redis-py) is already available; no new databases or services.
2. **Zero new dependencies** — All mechanisms use existing imports (redis, contextvars, threading).
3. **Backward-compatible** — Existing callers see 429s only if they exceed caps.
4. **Configurable without code change** — Caps and limits driven by env vars.
5. **Observable** — Every search call is countable in metrics; callers see remaining budget in response headers.
6. **Decoupled per-request and per-client controls** — Two independent mechanisms with different enforcement points.

## Considered Options

| Option | Approach | Decision | Rationale |
|--------|----------|----------|-----------|
| **A: Valkey sliding window + contextvar per-request counter** | ContextVar tracks search count per request; Valkey tracks sliding window per client IP | ✅ Chosen | No new dependencies; uses existing Redis/Valkey; contextvar is request-scoped without middleware changes |
| **B: Third-party rate limiter (slowapi, pyrate-limiter)** | Library-provided decorators and middleware | ❌ Rejected | Adds dependency; decorator approach doesn't integrate with internal `SearXNGClient` calls; less control over budget tracking |
| **C: Proxy-level rate limiting (nginx, Traefik)** | Rate limit at reverse proxy before requests reach agent-svc | ❌ Rejected | Can't distinguish search vs scrape requests; can't track per-search budget within a request |
| **D: In-memory only** | Use process-local dicts for rate tracking | ❌ Rejected | Doesn't survive restart; doesn't share across multiple agent-svc workers |

## Decision Outcome

Chosen option: **A — Valkey sliding window + contextvar per-request counter**, for the following architecture:

### Two independent mechanisms

**1. Per-request search cap** — Counts searches within a single HTTP request. Enforced inside `SearXNGClient.search()` via a `contextvars.ContextVar`. A `max_searches` limit is set at the client level (or via settings). When a single request tries to make more than `AGENT_MAX_SEARCHES_PER_REQUEST` search calls, a `RateLimitedError` is raised.

**2. Per-client sliding-window rate limit** — Counts search calls from a client IP over a 60-second sliding window. Enforced as a FastAPI dependency on search/answer/agent endpoints, using Valkey `INCR` + `EXPIRE` for the window tracking. Returns 429 when exceeded.

### New Components

1. **`agent-svc/agent/rate_limiter.py`** — Sliding window rate limiter using Valkey
2. **`RateLimitedError`** in `exceptions.py` — New exception class (429, code=RATE_LIMITED)
3. **New settings** in `settings.py`:
   - `AGENT_MAX_SEARCHES_PER_REQUEST: int = 5`
   - `AGENT_SEARCH_RATE_LIMIT: str = "10/60s"`

### Integration Points

| Component | What changes | How |
|-----------|-------------|-----|
| `SearXNGClient.search()` | Check per-request cap via contextvar | Before HTTP call, check contextvar search count < max; raise `RateLimitedError` if exceeded |
| `api.py` (answer, agent endpoints) | Initialize contextvar + check per-client rate | Set contextvar to 0; check Valkey sliding window before dispatching |
| `worker.py` `_process_agent_async()` | Initialize contextvar for background jobs | Set contextvar to 0; no per-client rate check (background jobs have no client IP) |
| `metrics.py` | Add search call counters | `search_calls_total{status="allowed\|rate_limited"}`, per-endpoint counts |
| `api.py` response handlers | Add budget response headers | `X-Search-Budget: remaining/max`, `X-Search-Rate-Remaining: remaining/window` |

### Per-Request Max-Searches: ContextVar Pattern

```python
import contextvars

_search_count: contextvars.ContextVar[int] = contextvars.ContextVar("search_count", default=0)

def reset_search_count(count: int = 0):
    _search_count.set(count)

async def check_search_budget(max_searches: int):
    current = _search_count.get()
    if current >= max_searches:
        raise RateLimitedError(
            detail=f"Search budget exceeded: {current}/{max_searches} searches used",
            details={"budget_used": current, "budget_max": max_searches},
        )
    _search_count.set(current + 1)
```

### Per-Client Rate Limit: Valkey Sliding Window

```python
import time
from redis import Redis

class SlidingWindowRateLimiter:
    def __init__(self, redis: Redis, limit: int, window_seconds: int):
        self.redis = redis
        self.limit = limit
        self.window = window_seconds

    async def check(self, key: str) -> tuple[bool, int]:
        """Returns (allowed, remaining) where remaining is count left in window."""
        now = int(time.monotonic())
        window_key = f"rate_limit:{key}:{now // self.window}"
        count = self.redis.incr(window_key)
        if count == 1:
            self.redis.expire(window_key, self.window * 2)
        remaining = max(0, self.limit - count)
        return count <= self.limit, remaining
```

### Response Headers

| Header | Example | Source |
|--------|---------|--------|
| `X-Search-Budget` | `3/5` | Per-request counter: remaining/max |
| `X-Search-Rate-Remaining` | `8/10` | Per-client window: remaining/limit |

### Metrics

```python
# New counters
METRICS.counter("search_calls_total", "Total search calls", ["status"]).inc({"status": "allowed"})
METRICS.counter("search_calls_total", "Total search calls", ["status"]).inc({"status": "rate_limited"})
```

### Env Vars

```bash
# ── Search Volume Controls ────────────────────────────────────
# Maximum search calls a single /answer or /agent request can make.
# AGENT_MAX_SEARCHES_PER_REQUEST=5

# Per-client sliding-window rate limit (searches / window_seconds).
# AGENT_SEARCH_RATE_LIMIT=10/60s
```

## Consequences

### Positive
- Default caps prevent any single request from burning >5 Brave calls
- Burst protection prevents 50+ search calls in 60s from a single client
- All search volume observable via logs and metrics
- Caps configurable without code changes
- Backward compatible — existing callers see 429s only if they exceed limits
- No new dependencies

### Negative
- Valkey key churn from sliding window (mitigated by 2x window TTL: each window key auto-expires)
- ContextVar must be explicitly reset in each entry point (easy to forget for new code paths)
- Per-client rate limit uses client IP which may be a NAT gateway (acceptable for current deployment)

### Risks
- False 429s if agent-svc runs behind a reverse proxy that doesn't forward `X-Forwarded-For` — mitigated by using `request.client.host` as fallback
- Background agent jobs don't have client IPs — they use a shared pool budget (configured separately, or use the per-request cap only)

## Links

- Issue #213: Search volume caps
- ADR-0031: Centralized Settings Object pattern (followed for new env vars)
- ADR-0032: Standardized Error Response Model (extends exception hierarchy)
- ADR-0018: Observability Infrastructure (extends metrics)

## Diagrams

```mermaid
flowchart TD
    subgraph "Per-Request Flow"
        A[HTTP Request] --> B{Endpoint Handler}
        B --> C[Reset search_count\ncontextvar to 0]
        C --> D{Check Valkey\nsliding window}
        D -->|429 exceeded| E[Return 429\nRateLimitedError]
        D -->|OK| F[Call research function]
        F --> G[SearXNGClient.search]
        G --> H{Check contextvar\nsearch_count < max?}
        H -->|No| I[Raise\nRateLimitedError]
        H -->|Yes| J[Increment contextvar\nDo HTTP search call]
        J --> K[Return results]
    end

    subgraph "Background Job Flow"
        L[Worker\n_process_agent_async] --> M[Reset search_count\ncontextvar to 0]
        M --> N[Call run_research]
        N --> G
    end

    subgraph "Valkey Sliding Window"
        O[Check key:\nrate_limit:{ip}:{window}] --> P[INCR key]
        P --> Q{Count <= limit?}
        Q -->|Yes| R[ALLOW\nset remaining header]
        Q -->|No| S[429 DENY\nRetry-After header]
    end
```
