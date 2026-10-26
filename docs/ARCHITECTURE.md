# Architecture

## Shape

One service. FastAPI serves the JSON API under `/api` and the built React app for every other path, so there is one
origin, one deploy, and no CORS. Postgres holds everything.

```
browser ──► FastAPI ──► /api/*  routers ──► services (business rules) ──► SQLAlchemy ──► Postgres
                    └─► /*      built React app (static files, SPA fallback)
automation (daily refresh) ──► /api/* with a bearer token
```

## Data

Each table keeps what the app filters and sorts on as real columns with constraints (a company's stage, a move's due
date and status, a person's part in the hire). The long tail of research (scores, reasons, sources, posting details)
sits in one JSONB column per table, so research can grow without migrations and nothing it writes is lost.

| Table | Holds |
| --- | --- |
| `companies` | a target company, its open role, its stage, and its research |
| `people` | someone around a hire: their part in it, how sure we are and why, drafts, status |
| `moves` | one dated thing to do: apply, a reach-out sequence to one person, a comment, a build |
| `activity` | the history, for the Plan page and for streaks |
| `radar_items` | roles the radar found, waiting to be added or dismissed |
| `prospects` | Fractional prospects: the research, and separately what the user did (never overwritten) |
| `magnets` | lead magnets built for a company |
| `settings` | small key/value settings (the candidate's name, snippets, goals) |
| `login_sessions`, `login_attempts` | sign-in |

Research written by automation never overwrites what the user changed: stage, notes, ticks and emails stay the user's.

## Security

- One user. The password is stored only as an argon2 hash in `PASSWORD_HASH`.
- A session is a random token in an HttpOnly, Secure, SameSite=Lax cookie. The database stores an HMAC of it, so a
  copy of the database can't be used to sign in.
- Every change needs the session's CSRF token in `X-CSRF-Token`. Automation uses `Authorization: Bearer <API_TOKEN>`.
- Eight failed sign-ins in 15 minutes lock the form.
- Strict Content Security Policy (`default-src 'self'`), no third-party scripts, fonts or styles at runtime.
- Logs record method, path, status and timing, never query strings or bodies.

## Scale

A single user's tracker is small (hundreds of companies, thousands of people and moves), but nothing assumes it:
list endpoints are paginated or bounded, the hot filters are indexed (`moves(status, due)`, `companies(stage)`,
`people(company_id)`), and the database pool is sized and pre-pinged so a restarted database doesn't surface as errors.

## Front end

React with TanStack Query for server state (cached, refetched on focus, optimistic updates with rollback), React Router
for screens, and Tailwind with the design's tokens (one ink, one indigo accent, amber for "in Toronto"). The API client
is generated from the backend's OpenAPI schema, so a backend change that breaks the front end fails type-checking in CI.
