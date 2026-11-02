# ADR 0002. Use Postgres as the job queue

Date: 2026-10-23 · Status: accepted. Carried over from the standalone events-leads app on 2026-11-01. Jobs now live in
`ev_jobs`, and the worker runs as a thread in the tracker's web process.

## Context

The events pipeline runs in the background and must survive crashes and redeploys. The usual choice is a broker such
as Redis or RabbitMQ with Celery or RQ. That is one more service to run, secure, monitor and pay for. It also splits
state between two systems, so a job can say "done" while the database write it depended on was rolled back.

## Decision

Jobs are rows in the `ev_jobs` table.

- Workers claim one with `SELECT ... FOR UPDATE SKIP LOCKED`, so two workers never take the same job.
- A job's own database writes and its completion commit in the same transaction.
- Failed jobs retry with exponential backoff.
- Jobs whose worker died are released after a timeout.

### Side effects outside the database

Postgres can roll back our writes but not a call to another service. A worker can stop after a paid call and before
its job commits, so the job runs again. Every handler that calls out must therefore make the retry safe, by following
the rules below. It must also have a test that runs it twice.

1. **Record the intent first, in its own commit.**
   - Before starting the call, write what is about to happen (the spend reservation, the search being started) and
     commit.
   - Right before the call, mark the reservation as started, which is one more short commit.
   - After the call, store the provider's handle right away, such as the Apify run ID on the run's event row.
2. **On retry, look before acting.**
   - **Reservation never marked started.** The call never happened. Release the reservation and start over.
   - **Handle stored.** Resume that call (poll that Apify run) instead of starting a new one. Settle the reservation
     from the provider's own record of what it charged.
   - **Started, but no handle** (the worker stopped during the call). Settle at the reserved amount, which is the
     most the call could cost, then start over. An unknown outcome counts as spent, never as freed.
     - An Apify run is capped at the reservation by `maxTotalChargeUsd`.
     - A Claude call is bounded by its prompt, `max_tokens` and `max_uses`.
   - **A sweeper backs this up.** It applies the same rules to any reservation still open an hour after it was made,
     so a run that died can't hold budget.
3. **Cache results by their natural key.** Model answers are cached by post and event, and Apollo results by
   LinkedIn URL. A retry re-reads the cache, so at most one in-flight batch is ever paid for twice, and that batch's
   cost was reserved.

## Consequences

- Postgres is the only stateful service, so job state and data can't disagree.
- Throughput is in the thousands of jobs per minute, far above what the external APIs allow anyway.
- If much more is ever needed, the queue can be swapped, because it sits behind a small interface: `enqueue`,
  `claim`, `complete` and `fail`.
