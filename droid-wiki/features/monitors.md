# Scheduled monitors

Active contributors: groktopus

## Purpose

The monitor system provides scheduled change detection for web pages. It periodically scrapes configured URLs, diffs the content against the previous version, and fires webhooks on changes.

## How it works

### Architecture

The monitor system uses Ofelia (a Docker-native cron scheduler) to run `python3 -m agent.monitor check_all` on a configurable schedule. Ofelia executes `docker exec agent-svc python3 -m agent.monitor` via the Docker socket.

### Check lifecycle

1. Ofelia triggers `check_all()` in `agent-svc/agent/monitor.py`
2. The function reads all monitor configs from a Valkey hash (`monitors` key)
3. For each monitor, `check_monitor()` runs:
   - Scrapes the URL via scraper-svc
   - Compares new content against `last_content` stored in the config
   - Computes a unified diff when content has changed
   - Updates the stored content and `last_checked` timestamp
   - Delivers a `monitor.changed` webhook event if content differs
   - Stores the check result in a Valkey list (`monitor:{id}:history`, last 50 checks)

### Monitors API

Monitors are managed through the Firecrawl v2-compatible API:

| Method | Endpoint | Description |
|---|---|---|
| POST | `/v2/monitor` | Create a monitor with URL, cron schedule, optional webhook |
| GET | `/v2/monitor` | List all monitors |
| GET | `/v2/monitor/{id}` | Get monitor status and history |
| PATCH | `/v2/monitor/{id}` | Update monitor config |
| DELETE | `/v2/monitor/{id}` | Delete a monitor |

## Key source files

| File | Purpose |
|---|---|
| `agent-svc/agent/monitor.py` | Monitor CRUD, check logic, diff computation |
| `agent-svc/agent/api.py` | Monitor route handlers |
| `ofelia/config.ini` | Ofelia cron schedule configuration |
| `docker-compose.yml` | Ofelia container definition with Docker socket mount |
