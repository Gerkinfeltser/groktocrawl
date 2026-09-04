# ADR-0063: Offload and Batch Session Persistence

- **Status:** accepted
- **Date:** 2026-09-04

## Context

The session state machine is asynchronous, but its Valkey client is
synchronous.  A step that stores many references therefore performs blocking
network calls on the FastAPI event loop, and each artifact append downloads and
rewrites all previous markdown.  Session metadata also needs an artifact
length without changing the API's character-count semantics for Unicode.

## Decision

Keep the synchronous `SessionStore` API for existing callers and add explicit
async methods that run each logical storage operation in `asyncio.to_thread`.
The asynchronous session path uses these methods exclusively, including lock
acquisition and release.  Reference commits use one transactional pipeline
with one TTL refresh per session key.  Artifact commits use Redis `APPEND` and
an `artifact_chars` metadata field; the field stores Python character length,
not Redis byte length.  Reads of sessions created before this field was added
fall back to one artifact read, after which the next append seeds the counter.

The existing JSON step-history key and reference hash remain unchanged for
compatibility.  Step commits are still serialized by the existing per-session
lock, while artifact and reference writes are atomic within their respective
transactions.  Missing sessions return the same false/none results as the
legacy methods, and storage errors remain visible to callers.

## Consequences

Async handlers no longer hold the event loop during synchronous Valkey I/O.
Reference command count is bounded per logical commit rather than multiplied
by the number of references, and artifact append traffic no longer scales with
the accumulated artifact.  A worker thread is occupied for each active
storage operation, and legacy sessions incur one migration read for artifact
length.  Step history remains JSON for public API compatibility and can be
migrated separately if append-only history storage becomes necessary.
