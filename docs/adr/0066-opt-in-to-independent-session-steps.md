# ADR-0066: Opt In to Independent Session Steps

- **Status:** accepted
- **Date:** 2026-09-04
- **Supersedes:** [ADR-0040](0040-session-protocol.md) for the opt-in mode only

## Context

Session steps historically hold one lock across remote search, scraping, and
storage.  That protects the legacy JSON history but makes independent search
and scrape requests wait behind network work.  Removing the lock globally
would allow dependent query and deepen actions to observe incomplete context.

## Decision

The session step API keeps serialized execution as its default and adds an
explicit `parallel` opt-in with an optional stable `idempotency_key`.  Only
search and scrape may use this mode.  They reserve a step identity and input
revision briefly, execute remote work without the session lock, and publish
through one guarded Redis commit.  At most eight independent reservations are
active per session.  The commit atomically appends step history,
references, and artifact text, increments the session revision, refreshes TTL,
and records the completed idempotency result.  A duplicate key returns the
recorded result; a pending duplicate is rejected without repeating external
work.  A failed or cancelled attempt releases its pending reservation for a
later retry.

Query and deepen remain serialized because they consume the session artifact
or refs.  Parallel commits accept a revision that has advanced since their
snapshot because independent search/scrape commits are append-only; a missing
session or invalid reservation rejects the late result.  Step indexes are
reserved before remote work, so concurrent commits retain stable citation IDs;
an abandoned reservation may leave a gap.  No queue or restart-safe execution
is introduced, and the existing admission and lock lease rules remain in
force for the default mode.

## Consequences

Independent remote actions can overlap while deterministic ref IDs and history
are preserved by the atomic commit script.  The caller must opt in and supply
the same idempotency key when retrying a completed request.  Parallel work can
finish in a different order from its reserved index, and a crashed worker's
reservation remains pending until its short lease expires.  Dependent actions
still see only committed evidence under the existing serialized protocol.
