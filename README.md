# GTM Tracker

A command center for running a job search the way a GTM engineer runs outbound: find the roles that fit, map everyone
around each hire, and work a short, dated list of moves every day.

- **Today** — the day's moves (apply, connect, email, bump), each with its draft ready to copy, plus new roles that fit
  and the people you're waiting on.
- **Pipeline** — every company on a board, from *Not started* to *Offer*, with its next step.
- **Company** — the role, and the whole circle of people around it: hiring manager, their boss, the team you'd join,
  the recruiter. Warmest first, with how sure we are of each person's part in the hire and where that came from.
- **Plan** — the calendar of upcoming moves and the history of what was done.
- **Radar** — new roles found every morning on LinkedIn and company job boards, filtered to what fits.
- **Fractional** — a daily list of funded startups to pitch for fractional GTM engineering, each with an offer and a
  free first deliverable.

The demo data in this repository is made up. Real data lives only in the database.

## Stack

| Layer | Choice |
| --- | --- |
| API | Python 3.12, FastAPI, SQLAlchemy 2, Alembic, Pydantic |
| Database | PostgreSQL (JSONB for research fields) |
| Front end | React 18, TypeScript (strict), Vite, TanStack Query, Tailwind CSS |
| API contract | OpenAPI schema generated from the API; typed client generated from the schema; CI fails if they drift |
| Tests | pytest against real Postgres; Vitest and Testing Library |
| Quality | Ruff, mypy `--strict`, ESLint, Prettier, CodeRabbit review on every pull request |
| Security | argon2 password hash, server-side sessions (hashed tokens), CSRF header, login rate limit, strict CSP |
| Deploy | One Docker image (API serves the built front end), migrations as a pre-deploy step |

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for how it fits together.

## Run it locally

You need Python 3.12 with [uv](https://docs.astral.sh/uv/), Node 22, and PostgreSQL.

```sh
psql postgres -c "CREATE ROLE gt LOGIN PASSWORD 'gt' CREATEDB"   # once: the role .env.example and the tests use
createdb -O gt gt_dev
createdb -O gt gt_test
cd backend
cp .env.example .env            # then fill in SECRET_KEY and PASSWORD_HASH (see the comments)
uv sync
uv run alembic upgrade head
uv run python -m app.cli seed-demo
uv run uvicorn app.main:app --reload

cd ../frontend
npm install
npm run dev                     # http://localhost:5173, proxied to the API on :8000
```

## Backups and moving data

- **Download backup** in the sidebar (or `GET /api/export`) saves everything as one JSON file.
- `python -m app.cli restore backup.json` loads a backup into an empty database.
- `python -m app.cli import-legacy export.json [fx.json]` brings data over from the first version of the tracker,
  keeping its ids. Fields without a column of their own are kept in each row's JSON.

## Checks

```sh
cd backend && uv run ruff format --check . && uv run ruff check . && uv run mypy app tests && uv run pytest --cov
cd frontend && npm run format:check && npm run lint && npm run typecheck && npm test && npm run build
```

Tests need a Postgres database at `TEST_DATABASE_URL` (default `postgresql+psycopg://gt:gt@localhost:5432/gt_test`).
The tests drop and recreate every table, so they refuse to run against a database whose name doesn't end in `_test`.

## License

MIT
