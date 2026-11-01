# ADR 0003. Put every external service behind an interface with a fake

Date: 2026-10-23 · Status: accepted. Carried over from the standalone events-leads app on 2026-11-01, without the email
service it no longer needs.

## Context

The events pipeline depends on four paid or rate-limited services: Claude, Apify, Apollo and, optionally, Reoon.
Calling them in tests has four problems:

- it is slow;
- it costs money;
- it needs secrets in CI;
- it gives different answers each time.

## Decision

Each service is a small Python protocol, for example `PostSearch.start(queries) -> run id`. Each protocol has two
implementations:

- a real one that talks HTTP;
- a **fake** that returns deterministic, realistic data.

`EVENTS_PROVIDERS=fake` selects the fakes, and the tracker uses `EVENTS_PROVIDERS=real` (the default). Response
parsing is tested against fixture files shaped like real responses, which hold synthetic data only, never real people.

## Consequences

- Tests run the whole pipeline offline, fast and free.
- A real API change can still break production. The parsers' contract tests catch shape changes we know about, but
  not new ones.
