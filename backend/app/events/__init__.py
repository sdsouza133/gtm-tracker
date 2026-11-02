"""The events tool: people going to (or just back from) the events a company's buyers attend, found in public
LinkedIn posts, kept when they fit the company's ICP, with verified work emails.

It came over from the standalone events-leads app and keeps its design: a Postgres job queue run by a worker thread,
paid calls that are safe to retry, and every outside service behind an interface with a fake. docs/events/ explains
the pipeline and holds the two decisions the code cites, ADR 0002 (the job queue and paid calls) and ADR 0003
(providers and fakes).
"""
