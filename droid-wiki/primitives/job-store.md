# Job store

Active contributors: groktopus

## Purpose

The job store provides Valkey-backed CRUD operations for all async job types (agent, crawl, extract, batch scrape, llmstxt). It is used by the API to create jobs and by workers to update status.

## Key schema

Jobs are stored across two Valkey keys:

- `job:{id}:meta` -- JSON with status, kind, created_at, completed_at, error
- `job:{id}:data` -- JSON with result data (set on completion)

Both keys expire after 24 hours via Valkey TTL.

## Methods

| Method | Description |
|---|---|
| `create_job(kind, payload)` | Creates a new job with UUID, returns the ID |
| `get_job(job_id)` | Returns job metadata with attached data |
| `complete_job(job_id, data)` | Sets status to "completed", stores result |
| `fail_job(job_id, error)` | Sets status to "failed", stores error |
| `cancel_job(job_id)` | Cancels a processing job, returns False if not found or already done |
| `list_active_jobs(kind, status, limit)` | Scans Valkey for jobs matching status and optional kind filter |

## Key source files

| File | Purpose |
|---|---|
| `agent-svc/agent/store.py` | JobStore class implementation |
