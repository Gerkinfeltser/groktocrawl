# Unified Activity Endpoint — Implementation Plan

## Goal

Add `GET /v2/activity` to GroktoCrawl, returning all active (in-progress / processing) jobs across all job types (crawl, agent, extract, batch_scrape, llmstxt). Update the CLI `active` command to consume it. This replaces the currently-broken `GET /crawl/active` path with a working, more general endpoint.

## Current Context

- **CLI** (`~/.local/bin/groktocrawl`): `cmd_active` calls `client.get_active_crawls()` → `GET /v2/crawl/active`. Expects response with `result.get("data", [])` where each item has `id` and `status`. Currently returns 404 because the route doesn't exist.
- **Server** (`agent-svc/agent/api.py`): All routes use `/v2/` prefix. Has `POST /v2/crawl`, `GET /v2/crawl/{id}`, `DELETE /v2/crawl/{id}` — but **no** `GET /v2/crawl/active` or any listing endpoint.
- **Store** (`agent-svc/agent/store.py`): `JobStore` has per-job CRUD only (`create_job`, `get_job`, `complete_job`, `fail_job`, `cancel_job`). No `list`/`scan` method. Keys stored as `job:{id}:meta` and `job:{id}:data` with 24h TTL.
- **Models** (`agent-svc/agent/models.py`): No activity-related response model.
- **Firecrawl v2 spec**: `GET /crawl/active` returns `{"success": true, "crawls": [...]}` with items having `id`, `teamId`, `url`, `status`, `options`. Also has a `GET /activity` endpoint (24-hour history with cursor pagination).

## Proposed Approach

Build a **unified activity endpoint** (`GET /v2/activity`) that serves active jobs across all types. This is more useful than a crawl-specific endpoint and matches the Firecrawl v2 pattern more closely (they have both `/crawl/active` and `/activity`).

Implementation uses Valkey `SCAN` — no new key structures, no migrations, no write-path changes. The SCAN is bounded by pagination and TTL expiration naturally prunes stale entries.

## Step-by-Step Plan

### Issue 1: Add `list_active_jobs()` to `JobStore`

**Files:** `agent-svc/agent/store.py`

Add a method that Valkey-SCANs keys matching `job:*:meta`, parses each, filters by status and optional kind:

```python
def list_active_jobs(self, kind: str | None = None, status: str = "processing", limit: int = 50) -> list[dict]:
    """List jobs by status, optionally filtered by kind.
    
    Uses Valkey SCAN with pattern `job:*:meta` — no dedicated index.
    For production at scale, replace with a sorted set or dedicated index.
    """
    active = []
    cursor = 0
    while len(active) < limit:
        cursor, keys = self.redis.scan(cursor=cursor, match="job:*:meta", count=100)
        # Fetch all candidates in one pipeline call
        pipe = self.redis.pipeline()
        for key in keys:
            pipe.get(key)
        results = pipe.execute()
        for raw in results:
            if raw is None:
                continue
            meta = json.loads(raw)
            if meta.get("status") != status:
                continue
            if kind and meta.get("kind") != kind:
                continue
            active.append(meta)
            if len(active) >= limit:
                return active
        if cursor == 0:
            break
    return active
```

**Key design decisions:**
- Returns a flat list of meta dicts (no attached data) — the listing endpoint doesn't need full results, just identity and status.
- Self-healing: Valkey TTL naturally clears completed/failed jobs after 24h, so SCAN won't accumulate stale entries forever.
- Pipeline batch fetching for performance: one round-trip per SCAN iteration instead of N round-trips.
- `limit` cap prevents unbounded responses. The consumer (API handler) can pass a sensible default (e.g. 50).

### Issue 2: Add `ActivityResponse` model

**Files:** `agent-svc/agent/models.py`

Add a lightweight response model:

```python
class ActivityItem(BaseModel):
    id: str
    kind: str
    status: str
    created_at: str
    completed_at: str | None = None
    url: str | None = None  # Extracted from payload for display

class ActivityResponse(BaseModel):
    success: bool = True
    data: list[ActivityItem] = Field(default_factory=list)
```

The `url` field is extracted from the job's `payload.url` (present in crawl, agent, extract, llmstxt jobs). If absent from payload, it's `None`.

### Issue 3: Add `GET /v2/activity` route handler

**Files:** `agent-svc/agent/api.py` (+ import of `ActivityResponse`)

```python
@router.get("/v2/activity", response_model=ActivityResponse)
async def list_activity(request: Request):
    """List all active/processing jobs across all types."""
    store: JobStore = request.app.state.job_store
    jobs = store.list_active_jobs(limit=50)
    items = []
    for job in jobs:
        payload = job.get("payload", {})
        url = payload.get("url") if isinstance(payload, dict) else None
        items.append(ActivityItem(
            id=job["id"],
            kind=job.get("kind", "unknown"),
            status=job.get("status", "processing"),
            created_at=job.get("created_at", ""),
            completed_at=job.get("completed_at"),
            url=url,
        ))
    return ActivityResponse(data=items)
```

### Issue 4: Update CLI `active` command

**Files:** `~/.local/bin/groktocrawl`

Three changes:

1. **`get_active_crawls()` → rename to `get_activity()`** and route to `GET /v2/activity`:
```python
def get_activity(self) -> Dict[str, Any]:
    return self._request("GET", "/activity")
```

Response handling in `cmd_active` already uses `result.get("data", [])` which matches the new `ActivityResponse.data` field. No parser changes needed — just the URL and method name.

2. **Update the human-readable output** to include the job kind and URL:
```python
for job in active:
    kind = job.get('kind', '?')
    url = job.get('url', '') or ''
    print(f"  {job.get('id','?')[:8]}  [{job.get('status','?')}]  {kind:12s}  {url}")
```

3. **Update CLI help text** from "List active crawl jobs" to "List active jobs" to reflect the unified scope.

### Issue 5: Add integration tests

**Files:** `tests/test_stack.py`

Add test cases that:

1. **`test_activity_endpoint_returns_active_jobs()`** — Create a crawl job, immediately query `GET /v2/activity`, verify it appears in the response with `status == "processing"` and `kind == "crawl"`.

2. **`test_activity_endpoint_multiple_types()`** — Create jobs of different types (agent, crawl, extract), verify all appear in the activity list.

3. **`test_activity_endpoint_empty()`** — Query activity when no jobs are running, verify empty `data` array.

4. **`test_activity_endpoint_excludes_completed()`** — Create a job, wait for completion, verify it no longer appears in active jobs.

5. **`test_cli_active_command()`** — Run `groktocrawl active --json`, verify valid JSON output with expected structure.

## Files Changed

| File | Change | Risk |
|------|--------|------|
| `agent-svc/agent/store.py` | Add `list_active_jobs()` method | Low — self-contained, no existing callers modified |
| `agent-svc/agent/models.py` | Add `ActivityItem`, `ActivityResponse` | Low — new models, no existing ones changed |
| `agent-svc/agent/api.py` | Add `GET /v2/activity` route + imports | Low — new route, no existing routes modified |
| `~/.local/bin/groktocrawl` | Update `get_active_crawls` → `get_activity`, update output | Medium — changing a CLI command's output format; existing scripts piping `active --json` may depend on key names |
| `tests/test_stack.py` | Add 5 new test functions | None |

## Validation

1. **Unit**: `list_active_jobs()` returns only `processing`-status jobs, respects `kind` filter, caps at `limit`, handles empty store gracefully
2. **Integration**: Full Docker stack test creates jobs and verifies they appear in activity
3. **CLI**: `groktocrawl active --json` returns valid JSON, `groktocrawl active` (human) shows readable table
4. **Existing behavior**: All existing endpoints continue to work — no code path removed or modified

## Risks & Trade-offs

- **SCAN performance at scale**: Valkey SCAN over `job:*:meta` keyspace is O(N) per call. With 24h TTL and typical usage (tens to low hundreds of concurrent jobs), this is fine. At thousands of concurrent jobs, the SCAN iteration count becomes non-trivial. Mitigation: add a Valkey Set index in a follow-up if needed.
- **CLI output format change**: `groktocrawl active` output currently doesn't work at all (404), so any change is an improvement. But `active --json` users who parse the output will now see `kind` and `url` fields added. This is additive, not breaking.
- **No pagination**: The initial implementation caps at 50 items without cursor-based pagination. Firecrawl's `/activity` endpoint supports cursor pagination. This is a known gap to address in a follow-up.

## Issue Filing Strategy

File as a single coordination issue describing the feature, with 3 sub-tasks referenced:

1. **Issue #A**: `store.py` — Add `list_active_jobs()` method
2. **Issue #B**: `api.py` + `models.py` — Add `GET /v2/activity` endpoint
3. **Issue #C**: CLI — Update `active` command
4. **Issue #D**: Tests — Activity endpoint integration tests

## PR Strategy

**Single PR** with 4 focused commits (one per issue), merged together:

```
feat(store): add list_active_jobs() method to JobStore
feat(api): add GET /v2/activity unified endpoint
feat(cli): update active command to use /v2/activity
test: add activity endpoint integration tests
```

If the change set is small enough, this could be 1-2 commits. The key constraint: each commit must leave the codebase in a working state (no broken intermediate states).
