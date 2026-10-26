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

## Rules worth knowing

- **One clock.** "Today" is the calendar day in `TIMEZONE` (America/Toronto). Every date the app writes or compares
  comes from `app/clock.py`, so a tick at 9 PM lands on that day, not on UTC's tomorrow.
- **One reach-out per person** (`app/services/reach.py`): email and connection request on Day 0; the LinkedIn message
  when they accept; one email bump 4 working days after the later first touch if they don't. A reply or closing it by
  hand ends it. Pure functions, tested against a table of worked examples.
- **Stages move forward on their own** (an email sent: Contacted; a reply: Replied; a call done: Call booked), and
  backwards only by hand. Parked, rejected and bench companies keep their moves but leave Today.
- **XP and streaks are computed on the server from the whole history.** Moves earn XP while they're done (untick a
  step and it's taken back); one-off wins are written to the history once: a call booked or an offer once per company
  (dragging a company back and forth earns nothing), a reply once per person.
- **Business rules raise `RuleError`** with a message the user can act on; the API turns it into a 409 (404 when the
  thing isn't there), and the front end shows the message.

## Security

- One user, signing in with Google, a password, or both.
  - **Google**: Google's own button (Google Identity Services) hands the page an ID token, and
    `POST /api/auth/google` checks it on the server with `google-auth`: Google's signature, `GOOGLE_CLIENT_ID` as the
    audience, the expiry, a verified email, and that email in `ALLOWED_EMAILS` (comma-separated, any case). Anyone
    else gets a 401. Without `GOOGLE_CLIENT_ID` the button doesn't show and the route answers 404.
  - **Password**: stored only as an argon2 hash in `PASSWORD_HASH`. Without one, the sign-in page shows only Google.
- Setting up Google sign-in: Google Cloud Console → APIs & Services → Credentials → Create credentials → OAuth client
  ID → Web application, with the site's address (and `http://localhost:5173` for local work) under Authorized
  JavaScript origins. No redirect URI or client secret is needed. Put the client ID in `GOOGLE_CLIENT_ID` (it's
  public: it's in every sign-in page) and the owner's Google address in `ALLOWED_EMAILS`.
- A session is a random token in an HttpOnly, Secure, SameSite=Lax cookie that lasts `SESSION_DAYS` (180 by default,
  365 at most), however the user signed in. The database stores an HMAC of it, so a copy of the database can't be
  used to sign in.
- Every change needs the session's CSRF token in `X-CSRF-Token`. Automation uses `Authorization: Bearer <API_TOKEN>`.
- Eight failed sign-ins (Google or password) in 15 minutes lock both for a while.
- `OPEN_ACCESS=true` turns the login off: anyone with the address can use the tracker. It is off unless set; missing
  sign-in settings never open the app, they just mean nobody can sign in.
- Work emails come from Apollo (`APOLLO_API_KEY`), and only while sign-in is on: with `OPEN_ACCESS` the enrich routes
  answer 409, so emails never sit in a tracker anyone can open. Today asks `POST /api/enrich/today` when it opens and a
  company panel asks `POST /api/companies/{id}/enrich`; each person is looked up once (`details.apollo_tried`), so a
  repeat call costs no credits. Apollo is asked for work emails only, never personal ones.
- `POST /api/restore` loads a backup into an empty tracker (for a server whose database is reachable only through the
  app). A tracker with any data refuses it.
- Strict Content Security Policy (`default-src 'self'`). The one exception is Google's sign-in button: its script,
  iframe and stylesheet from `https://accounts.google.com`. Opener policy is `same-origin-allow-popups`, so Google's
  sign-in popup can hand the token back.
- Logs record method, path, status and timing, never query strings or bodies.

## Scale

A single user's tracker is small (hundreds of companies, thousands of people and moves), but nothing assumes it:
list endpoints are paginated or bounded, the hot filters are indexed (`moves(status, due)`, `companies(stage)`,
`people(company_id)`), and the database pool is sized and pre-pinged so a restarted database doesn't surface as errors.

## Front end

React with TanStack Query for server state (cached, refetched on focus, optimistic updates with rollback), React Router
for screens, and Tailwind with the design's tokens (one ink, one indigo accent, amber for "in Toronto"). The API client
is generated from the backend's OpenAPI schema, so a backend change that breaks the front end fails type-checking in CI.
