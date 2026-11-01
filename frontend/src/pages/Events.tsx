import { useId, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";

import { type EventsHome, useEventsHome, useHoldNewRuns, useStartEventRun } from "@/api/hooks";
import { RunRow } from "@/components/EventRunRow";
import { notify } from "@/components/Toast";
import { Button, Card, EmptyState, PageHeader } from "@/components/ui";
import { blocked, usd } from "@/lib/events";

const field = "min-h-[38px] rounded-lg border border-line bg-surface px-3 text-sm";

function Today({ home }: { home: EventsHome }) {
  const hold = useHoldNewRuns();
  const { today, queue } = home;
  const used = today.spent_usd + today.reserved_usd;
  return (
    <Card className="flex flex-wrap items-center justify-between gap-4 p-4">
      <div className="min-w-0 text-sm">
        <p className="text-[15px] font-semibold">
          {usd(used)} of {usd(today.cap_usd)} spent today
          <span className="font-normal text-muted">
            {" "}
            · {today.runs_started} run{today.runs_started === 1 ? "" : "s"} started (UTC day)
          </span>
        </p>
        <p className="text-[13px] text-muted">
          Each run spends up to {usd(home.run_budget_usd)} on Claude and Apify, plus Apollo credits for emails. Jobs:{" "}
          {queue.running} running, {queue.due} waiting, {queue.later} later
          {queue.failed ? `, ${queue.failed} failed` : ""}.
        </p>
        {home.paused_by_setting && (
          <p className="mt-1 text-[13px] text-warm">
            EVENTS_PAUSE_NEW_RUNS is set, so no paid call starts until it's unset.
          </p>
        )}
      </div>
      {!home.open_access && (
        <Button
          disabled={hold.isPending}
          onClick={() =>
            hold.mutate(!home.paused, {
              onSuccess: () => notify(home.paused ? "New runs can start again" : "New runs are on hold"),
            })
          }
        >
          {home.paused ? "Let new runs start" : "Hold new runs"}
        </Button>
      )}
    </Card>
  );
}

function StartForm({ home }: { home: EventsHome }) {
  const [website, setWebsite] = useState("");
  const start = useStartEventRun();
  const navigate = useNavigate();
  const inputId = useId();
  const reason = blocked(home);

  function submit(e: FormEvent) {
    e.preventDefault();
    start.mutate(
      { website: website.trim() },
      {
        onSuccess: (run) => navigate(`/events/${run.id}`),
      },
    );
  }

  return (
    <Card className="p-4">
      <form className="flex flex-wrap items-end gap-3" onSubmit={submit}>
        <label htmlFor={inputId} className="flex min-w-[240px] flex-1 flex-col gap-1 text-sm">
          <span className="font-medium">A company's website</span>
          <input
            id={inputId}
            className={field}
            value={website}
            onChange={(e) => setWebsite(e.target.value)}
            placeholder="acme.com"
            disabled={Boolean(reason)}
          />
        </label>
        <Button type="submit" variant="primary" disabled={Boolean(reason) || !website.trim() || start.isPending}>
          Find their event-goers
        </Button>
      </form>
      <p className="mt-2 text-[13px] text-muted">
        {reason ||
          "It reads the site, works out who they sell to and the events those buyers go to, and waits for you to approve the plan before searching."}
      </p>
    </Card>
  );
}

export function EventsPage() {
  const home = useEventsHome();
  return (
    <div className="flex max-w-4xl flex-col gap-6">
      <PageHeader eyebrow="People going to the events a company's buyers attend" title="Events" />
      {home.isPending && <p className="text-sm text-muted">Loading…</p>}
      {home.isError && <p className="text-sm text-bad">Couldn't load the events tool. {home.error.message}</p>}
      {home.data && (
        <>
          <Today home={home.data} />
          <StartForm home={home.data} />
          {home.data.runs.length ? (
            <Card>
              <ul className="divide-y divide-line" aria-label="Runs">
                {home.data.runs.map((run) => (
                  <RunRow key={run.id} run={run} />
                ))}
              </ul>
            </Card>
          ) : (
            <EmptyState title="No runs yet">Runs and their lists are kept for 30 days.</EmptyState>
          )}
        </>
      )}
    </div>
  );
}
