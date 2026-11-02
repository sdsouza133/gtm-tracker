# The events tool

The events tool finds the people going to, or just back from, the events a company's buyers attend. It looks for them
in public LinkedIn posts, keeps the ones who fit the company's ICP, and finds their verified work emails. It came over
from the standalone events-leads app (events.theb2bdynamics.com) and now runs inside the tracker, behind the
tracker's sign-in, as an internal tool.

The code is in `backend/app/events/` and the tests are in `backend/tests/events/`. Its tables all start with `ev_`.

## What changed in the move

These came out, because they only served outside companies using the tool themselves:

- sign-in with a work email;
- one free run per company, and operator grants for more;
- emailing the finished list;
- rate limits on sign-ups;
- the manual AI mode, where an operator answered Claude's questions when no key was set.

You start a run for any website, and you review its plan and read its list in the tracker.

## Where it is in the tracker

- **The Events tab** (`/events`) shows:
  - the day's spend against the cap, and the job queue;
  - a switch that holds new runs;
  - a box to start a run for any website;
  - the latest runs.
- **A run's page** (`/events/:id`) depends on where the run is:
  - **Working:** its steps, and the posts, people and emails found so far. It checks back every few seconds.
  - **Awaiting approval:** the plan to edit. That covers the ICP (summary, industries, regions, company sizes,
    buyers, excluded titles) and the events, with up to three picked and their LinkedIn searches. You can also add up
    to three events you know. "Find the people" approves the plan and starts the search.
  - **Ready:** the list, best fit first, with a CSV download.
  - **Stopped:** why it stopped.
  - **Any time before it finishes:** a Cancel button.
- **A company's panel** has an "Event leads" section. It starts a run from the company's website, linked to the
  company, and lists that company's runs.
- **The API** is under `/api/events` (`app/api/events.py`, over `app/events/views.py`).
  - Every route needs sign-in.
  - While the tracker runs with `OPEN_ACCESS` (no sign-in), the tool is off and answers 409, because its lists hold
    work emails. The overview route stays on, to say so.

## How it runs

The tool has no service of its own. When the tracker starts, it starts one worker thread (`app/events/worker.py`).
The worker claims jobs from `ev_jobs` and runs them (see [ADR 0002](adr-0002-postgres-job-queue.md)).

- **The worker needs three keys:** `ANTHROPIC_API_KEY`, `APIFY_TOKEN` and `APOLLO_API_KEY`, the same keys the rest of
  the tracker uses (and `EVENTS_REOON_API_KEY` with `EVENTS_REOON_ENABLED`). Without them it runs only its
  housekeeping and the 30-day deletion, and the Events page says which keys are missing. A run whose job it gives
  up on still fails.
- **`EVENTS_WORKER=false`** turns the worker off. The tests do this.
- **A redeploy** stops the worker. It takes no new job, and waits up to 20 seconds for the one it's running. A job about
  to make a paid call goes back to the queue, and a job cut off mid-way is picked up again once its heartbeat goes
  quiet (5 minutes).
  - Railway only waits for this if the service has `RAILWAY_DEPLOYMENT_DRAINING_SECONDS` set to 30 or more (its
    default is 0). Without it, a redeploy can cut a job off, and the job is then picked up again as above. A paid call
    cut off that way counts at its full reserved cost.
- **Every outside service is behind an interface with a fake** (see
  [ADR 0003](adr-0003-providers-behind-interfaces.md)). `EVENTS_PROVIDERS=fake` runs the whole pipeline offline.

## The pipeline

A run moves through these states. Each arrow is one background job, and every job is safe to run twice.

```text
analyzing ─► awaiting_approval ─► collecting ─► qualifying ─► enriching ─► ready ─► expired (after 30 days)
    │                                  │             │            │
    └──────────────────────────────────┴─────────────┴────────────┴─► failed     (canceled from any step before ready)
collecting / qualifying wait as waiting_for_budget when the day's cap is reached, and go on the next UTC day
```

1. **analyze** (`pipeline/analyze.py`), two jobs.
   - `analyze_site` reads the home page and up to four pages about the company's customers, then asks Claude for the
     ICP. If the site can't be read or has too little text, the run fails with the reason instead of a guess.
   - `find_events` asks Claude, with live web search, for real events. It builds up to four LinkedIn searches per
     event and stores them on the run, for you to edit before approving.
2. **approve** (`pipeline/collect.py`, `approve`) stores the events you picked (at most three) and queues one
   `collect_event` job for each.
3. **collect**, one job per event.
   - It reuses any search a run made for the same event in the last `EVENTS_SEARCH_CACHE_DAYS` (3). A run waits for
     another run's search of the same event rather than pay twice.
   - The rest go into one Apify run, capped by `maxTotalChargeUsd`.
   - A search that fails is tried once more, then only its event is dropped. The run fails only if no event could be
     searched.
4. **qualify**, one job per run.
   - Text rules (`pipeline/rules.py`) label the obvious posts for free, and Claude labels the rest, 25 posts per call.
     Labels are cached per post and event, so later runs reuse them.
   - Each person who was there (attending, attended, speaking, exhibiting) becomes a candidate with their most telling
     post.
   - Anyone whose headline already rules them out is kept with the reason and skipped by the paid steps: an excluded
     title, a student, or someone at the company itself.
5. **enrich**, one job per run.
   - Apollo matches candidates by LinkedIn URL, ten per call, likeliest fits first. Its answer is cached on the person
     for `EVENTS_PERSON_CACHE_DAYS` (30).
   - Each person is scored against the ICP (`pipeline/scoring.py`), and the reasons are kept.
   - The best `EVENTS_MAX_LEADS` (50) with a verified email and a score of at least `EVENTS_MIN_ICP_SCORE` (40) make
     the list.
   - With `EVENTS_REOON_ENABLED`, those addresses get a second check.
   - The run is then ready, and its list is kept for `EVENTS_RESULTS_DAYS` (30).

## Money

- **Claude and Apify** are billed in dollars. Each run has `EVENTS_RUN_BUDGET_USD` ($3), of which
  `EVENTS_ANALYSIS_BUDGET_USD` ($0.50) is the most it spends before you approve. Every run also counts against the
  day's `EVENTS_DAILY_CAP_USD` ($20).
- **Reserving before calling.** Each paid call first reserves its estimate against both the run's cap and the day's
  cap, in one transaction, and settles the actual cost afterwards. Apify runs carry `maxTotalChargeUsd`, so even a
  runaway search can't go past its reservation.
- **Apollo** is billed in credits: a run uses at most `EVENTS_APOLLO_CREDITS_PER_RUN` (150), one per person found.
- **Stopping new spend.** `EVENTS_PAUSE_NEW_RUNS` stops all new paid calls: jobs that would make one wait 5 minutes
  and try again.

## Deleting personal data

The `retention` job runs every hour (`pipeline/retention.py`) and deletes data once it's 30 days old:

- a run's list once its results expire, or 30 days after a run failed or was canceled. A run still under way
  that hasn't moved for 30 days (a key went missing, say) is stopped, and its list deleted;
- posts no list holds, with their labels;
- people no list holds;
- searches;
- finished jobs.

A list that is still shown keeps everyone on it.

The tracker's backups leave the `ev_` tables out, so restoring an old backup can't bring deleted data back.

## Tables

| Table | Holds |
| --- | --- |
| `ev_runs` | One per search: the website, the tracker company it's for (optional), status, ICP, suggested events, spend |
| `ev_events`, `ev_run_events` | Events, and which ones (and which searches) a run uses |
| `ev_posts`, `ev_event_posts`, `ev_search_cache` | The shared post cache and the searches already run |
| `ev_post_labels` | Attendance label per post and event, and whether a rule or Claude gave it |
| `ev_people` | One row per LinkedIn profile, with cached Apollo data |
| `ev_run_leads` | A run's candidates and its list, with ICP score and reasons |
| `ev_jobs` | The job queue |
| `ev_spend`, `ev_budget_days` | Every paid call, and each day's running total for the daily cap |
| `ev_flags` | Switches flipped from the Events page, such as pausing new runs |
