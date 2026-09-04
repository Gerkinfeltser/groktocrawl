# ADR-0065: Stream Discovery Acquisitions as Queries Complete

- **Status:** accepted
- **Date:** 2026-09-04

## Context

Deep research runs its subqueries concurrently, but the previous discovery
implementation waited for every query before starting any page acquisition.
That barrier delayed the first useful source when one query was slow.

## Decision

Run a bounded producer/consumer acquisition loop. As each search task completes,
its unique candidates may enter the bounded scrape set while other searches are
still running. Search results and final artifacts are reconstructed in query
order and then passed through the existing deterministic ranking and credit
budget rules. A source callback forwards successful acquisitions to the
research event loop immediately. Failures degrade as before, retryable rate
limits propagate, and cancellation awaits all search and scrape tasks.

## Consequences

The first source can be acquired before the full discovery fan-out completes,
reducing time to useful evidence. A small bounded amount of speculative work
may be discarded when later ranking changes the selected evidence set. Fresh
contexts and the request-scoped source registry continue to prevent duplicate
or incompatible reuse.

## Alternatives considered

- Wait for all searches before scraping: preserves the barrier and delays the
  first source.
- Start an unbounded scrape task for every result: reduces latency at the cost
  of uncontrolled outbound work and credit violations.
- Emit source events after discovery: preserves event ordering but hides the
  actual acquisition progress from streaming clients.
