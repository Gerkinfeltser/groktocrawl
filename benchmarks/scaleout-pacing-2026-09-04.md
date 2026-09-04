# Distributed pacing validation

The production Lua reservation script was executed against an isolated local
Valkey instance with persistence disabled. Twelve concurrent reservations for
one origin and a 100 ms spacing returned delays of:

`0, 99, 199, 299, 399, 499, 599, 699, 799, 899, 999, 1099` milliseconds.

Each caller received a distinct slot. A further call with a 10 ms maximum wait
was rejected without advancing the reservation key. This validates the atomic
script and shared clock, not actual scrape completion or browser throughput.

The focused unit suite passed 31 tests, including replica key consistency,
read-only tier checks, unavailable coordination, queue exhaustion, cancellation,
and the unchanged single-node politeness behavior. Compose resolved the real
base+scaleout override with scraper host ports removed, gateway host port 8001,
and API browser admission budget 128. The additional Scraper Scale-Out CI lane
exercises gateway routing at 1/2/4 replicas and backend-failure recovery using
bounded acquisition twins; its JSON artifact records single-request median,
concurrent request p50/p95, throughput, and number of backends reached.
