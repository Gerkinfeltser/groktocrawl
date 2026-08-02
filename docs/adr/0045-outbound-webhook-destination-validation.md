# Outbound Webhook Destination Validation

* Status: accepted
* Deciders: GroktoCrawl maintainers
* Date: 2026-08-01

## Context and Problem Statement

Webhook delivery accepts a user-supplied URL and posts to it without applying
the shared private-host SSRF guard used by scraping. If the API is exposed or
authentication is misconfigured, an attacker can use the service to reach
loopback, RFC 1918, link-local, multicast, or other restricted network
destinations. Redirect handling could turn an initially safe URL into a
restricted destination. The normal job webhook path (`agent/webhook.py`) and
the monitor webhook path (`agent/monitor.py`) both have the gap.

## Decision Drivers

* Webhook delivery must never reach private, internal, or otherwise restricted
  destinations, regardless of how the URL was supplied.
* Normal job webhooks and monitor webhooks must share the same validation
  behavior.
* Delivery stays best effort (per ADR-0012 and ADR-0035): a rejected destination
  must not fail the underlying job or monitor check.
* Reuse the existing shared guard rather than duplicating policy per service.

## Considered Options

* **A. Dispatch-time validation in the shared webhook path** — validate the
  destination immediately before every POST, using one shared helper that wraps
  the existing `common.url.is_private_host` guard plus scheme and hostname
  checks. Rejected destinations are skipped with a warning; jobs and checks
  complete normally.
* **B. Request-time model validation** — reject webhook configurations at API
  request time by converting the free-form `webhook` dict into a validated
  model. Covers only the API surface; plan, crawl-stream, and monitor
  configuration paths still need separate handling, and rejects the request
  itself rather than the delivery.
* **C. No validation** — relies on API auth and operator trust. Rejected: this
  is the vulnerability being fixed.

## Decision Outcome

Adopt option A. `common.url.validate_outbound_webhook_url()` is the single
shared validator: it requires an explicit `http`/`https` scheme and a hostname,
and rejects any host that `is_private_host()` flags (RFC 1918, loopback,
link-local, IPv6 ULA/loopback, multicast, cloud metadata endpoints,
`.docker.internal`, DNS names resolving to restricted addresses, and
unresolvable DNS fail closed). The multicast ranges `224.0.0.0/4` and
`ff00::/8` were added to the shared private-network definitions to close the
multicast gap. IPv6 forms that embed an IPv4 destination are unwrapped to
their embedded IPv4 before checks — IPv4-mapped (`::ffff:a.b.c.d`),
deprecated IPv4-compatible (`::a.b.c.d`), 6to4 (`2002::/16`), Teredo
(`2001:0000::/32`, de-obfuscated client IPv4), and NAT64 well-known prefix
(`64:ff9b::/96`) — so `::ffff:127.0.0.1`, `2002:0a00:0001::`, and
`64:ff9b::a9fe:a9fe` (metadata) are rejected rather than treated as public,
while public embedded destinations (e.g. `2002:5db8:d822::`) remain allowed.

One shared async gate, `ensure_deliverable_webhook_destination()`, is used
before every webhook dispatch, so both paths share identical validation
behavior:

* `agent/webhook.py` — `deliver_webhook()` gates the delivery retry loop on the
  shared gate.
* `agent/monitor.py` — both `check_monitor()` and `run_search_monitor()` gate
  the notify POST on the shared gate; the check result is stored normally even
  when delivery is skipped.

The gate runs validation in a worker thread via `asyncio.to_thread()` so the
event loop is not blocked; transient DNS failures (`EAI_AGAIN`) are retried
with exponential backoff inside the gate, while permanent rejections
(private/restricted destinations, malformed URLs) skip immediately. Redirects
are disabled (`follow_redirects=False`) on all webhook HTTP clients so a
validated public destination can never be redirected to a restricted host.

## Consequences

* Restricted webhook destinations are rejected on every delivery path with a
  single shared policy, and the same policy now covers multicast for scraping
  paths too.
* A rejected destination is skipped silently from the perspective of the job or
  monitor result; operators see the warning in service logs.
* DNS-based validation performs one lookup per delivery; unresolvable
  destinations fail closed.
* The resolver is not rebound to the validated IP — a DNS rebinding attack
  window remains between validation and connection, matching the behavior of
  the existing scrape-side guard. This is accepted for now and should be
  revisited if the outbound proxy layer or a dedicated HTTP client is added.
* Request-time rejection of invalid webhook URLs is out of scope; delivery-time
  validation covers every configuration path uniformly.

## Links

* [ADR-0012: Webhook Delivery for Async Endpoints](0012-webhook-delivery-for-async-endpoints.md)
* [ADR-0035: Graceful Shutdown for Fire-and-Forget Tasks](0035-graceful-shutdown.md)
* GitHub issue [#469](https://github.com/groktopus/groktocrawl/issues/469)
