---
name: Bug report
about: Report something that isn't working
title: ''
labels: bug
assignees: ''

---

## Bug Description

A clear, concise description of the bug.

## Steps to Reproduce

1. Set up: `docker compose up --build -d` (or relevant config)
2. Call: `./groktocrawl scrape <url>` (or API call)
3. See error

```
Include full error output here
```

## Expected Behavior

What should happen instead.

## Actual Behavior

What actually happens — include full error output, HTTP status codes, and any relevant logs.

## Environment

- **OS:** (e.g., Linux x86_64, macOS ARM64)
- **Docker version:** `docker --version`
- **GroktoCrawl version/commit:** (e.g., commit abc1234, tag v0.1.0)
- **.env config:** (redact API keys)

## Logs

Relevant output from `docker compose logs <service>`:

```
(paste logs here)
```

## Additional Context

Screenshots, config files, or anything else that helps diagnose the issue.
