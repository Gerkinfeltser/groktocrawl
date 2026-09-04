# BrowserPool concurrency evidence

Run on 2026-09-04 with the production `BrowserPool` and Playwright on the
local macOS host. The benchmark fulfills every page through Playwright route
interception, so it makes no origin or external network requests. Each
synthetic session runs three page fetches with at most three contexts in
parallel. The 1, 2, and 4 pool cases use independent `BrowserPool` instances,
each with `max_processes=1`, and the eight-session case assigns sessions
round-robin across those pools.

The raw measurements are in
[`browser_pool_concurrency-results.json`](browser_pool_concurrency-results.json).

| Pools | Sessions | Pages | Throughput (pages/s) | Session p50/p95 (s) | Context acquire p50/p95 (s) | Peak descendant RSS / PIDs |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 1 | 3 | 1.040 | 2.448 / 2.448 | 0.855 / 0.875 | 941 MiB / 11 |
| 1 | 8 | 24 | 4.959 | 4.329 / 4.386 | 0.417 / 0.421 | 3,880 MiB / 52 |
| 2 | 1 | 3 | 1.356 | 1.733 / 1.733 | 0.337 / 0.337 | 1,002 MiB / 11 |
| 2 | 8 | 24 | 5.699 | 4.032 / 4.093 | 0.448 / 0.464 | 4,105 MiB / 56 |
| 4 | 1 | 3 | 1.430 | 2.019 / 2.019 | 0.370 / 0.371 | 1,037 MiB / 11 |
| 4 | 8 | 24 | 5.781 | 3.910 / 3.951 | 0.652 / 0.660 | 4,707 MiB / 61 |

All 24-page cases returned identical content hashes, and every pool reported
zero processes after `finally` cleanup. The one-process-per-pool bound was
held throughout; the process-tree samples include Playwright's driver and
Chromium descendants. RSS, PID, and CPU values are best-effort snapshots from
`ps`, so they are directional rather than a resource contract.

These results show bounded local pool behavior and context concurrency. They
do not measure Docker replica routing, the scraper HTTP server, full research
sessions, provider latency, LLM work, or production browser capacity. They
must not be added to the gateway-twin throughput numbers as an aggregate
production claim.

Command:

```sh
PYTHONPATH=agent-svc:scraper-svc:llm-svc:. \
  /Volumes/tank01/magnus/git/groktocrawl/.venv/bin/python \
  benchmarks/browser_pool_concurrency.py \
  --output benchmarks/browser_pool_concurrency-results.json
```
