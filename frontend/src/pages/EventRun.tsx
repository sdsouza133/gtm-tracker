import { clsx } from "clsx";
import { Check, Download, ExternalLink, Mail } from "lucide-react";
import { useId, useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";

import {
  type EventLead,
  type EventPlan,
  type EventRun,
  type S,
  useAddEvent,
  useCancelEventRun,
  useEventLeads,
  useEventRun,
  useSavePlan,
} from "@/api/hooks";
import { notify } from "@/components/Toast";
import { Button, Card, Chip, EmptyState, PageHeader } from "@/components/ui";
import { formatDateTimeDay, formatDay } from "@/lib/format";
import { toEventCsv } from "@/lib/leads";
import { safeUrl } from "@/lib/safe";
import {
  type Buyer,
  type Draft,
  SIZES,
  type Seniority,
  bodyOf,
  draftOf,
  lines,
  planProblem,
  statusTone,
  usd,
} from "@/lib/events";

const field = "min-h-[38px] rounded-lg border border-line bg-surface px-3 text-sm";
const SENIORITIES: [Seniority, string][] = [
  ["owner", "Owner"],
  ["founder", "Founder"],
  ["c_suite", "C-suite"],
  ["partner", "Partner"],
  ["vp", "VP"],
  ["head", "Head"],
  ["director", "Director"],
  ["manager", "Manager"],
  ["senior", "Senior"],
  ["entry", "Entry level"],
];
const MAX_BUYERS = 5;
const FINISHED = new Set(["ready", "failed", "canceled", "expired"]);

function when(start?: string | null, end?: string | null): string {
  const first = start ?? end;
  const last = end ?? start;
  if (!first || !last) return "";
  return first === last ? formatDay(first) : `${formatDay(first)} – ${formatDay(last)}`;
}

// ---------------------------------------------------------------------------------------------------- the plan
function TextField(props: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  hint?: string;
  rows?: number;
}) {
  const id = useId();
  return (
    <label htmlFor={id} className="flex flex-col gap-1 text-sm">
      <span className="font-medium">{props.label}</span>
      {props.rows ? (
        <textarea
          id={id}
          rows={props.rows}
          className={clsx(field, "py-2")}
          value={props.value}
          onChange={(e) => props.onChange(e.target.value)}
        />
      ) : (
        <input id={id} className={field} value={props.value} onChange={(e) => props.onChange(e.target.value)} />
      )}
      {props.hint && <span className="text-[13px] text-muted">{props.hint}</span>}
    </label>
  );
}

function Toggle<T extends string>(props: {
  options: [T, string][];
  chosen: T[];
  onChange: (v: T[]) => void;
  legend: string;
}) {
  return (
    <fieldset className="flex flex-col gap-1 text-sm">
      <legend className="mb-1 font-medium">{props.legend}</legend>
      <div className="flex flex-wrap gap-x-4 gap-y-1">
        {props.options.map(([value, label]) => (
          <label key={value} className="inline-flex items-center gap-1.5">
            <input
              type="checkbox"
              checked={props.chosen.includes(value)}
              onChange={(e) =>
                props.onChange(e.target.checked ? [...props.chosen, value] : props.chosen.filter((v) => v !== value))
              }
            />
            {label}
          </label>
        ))}
      </div>
    </fieldset>
  );
}

function IcpEditor({ draft, set }: { draft: Draft; set: (d: Draft) => void }) {
  const buyer = (i: number, change: Partial<Buyer>) =>
    set({ ...draft, buyers: draft.buyers.map((b, j) => (j === i ? { ...b, ...change } : b)) });
  return (
    <Card className="flex flex-col gap-4 p-4">
      <h2 className="text-[17px] font-semibold">Who they sell to</h2>
      <TextField
        label="In a sentence or two"
        rows={2}
        value={draft.summary}
        onChange={(summary) => set({ ...draft, summary })}
      />
      <div className="grid gap-4 sm:grid-cols-2">
        <TextField
          label="Industries"
          rows={4}
          value={draft.industries}
          onChange={(industries) => set({ ...draft, industries })}
          hint="One per line, up to 12."
        />
        <TextField
          label="Countries or regions"
          rows={4}
          value={draft.regions}
          onChange={(regions) => set({ ...draft, regions })}
          hint="One per line, up to 12."
        />
      </div>
      <Toggle
        legend="Company size (people)"
        options={SIZES.map((s) => [s, s])}
        chosen={draft.sizes}
        onChange={(sizes) => set({ ...draft, sizes })}
      />
      <div className="flex flex-col gap-3">
        <h3 className="text-sm font-medium">Buyers</h3>
        {draft.buyers.map((b, i) => (
          <div key={i} className="flex flex-col gap-2 rounded-lg border border-line p-3">
            <div className="grid gap-3 sm:grid-cols-2">
              <TextField label={`Buyer ${i + 1}`} value={b.label} onChange={(label) => buyer(i, { label })} />
              <TextField
                label="Words in their job titles"
                rows={3}
                value={b.keywords}
                onChange={(keywords) => buyer(i, { keywords })}
                hint="One per line."
              />
            </div>
            <Toggle
              legend="Seniority"
              options={SENIORITIES}
              chosen={b.seniorities}
              onChange={(seniorities) => buyer(i, { seniorities })}
            />
            {draft.buyers.length > 1 && (
              <Button
                variant="quiet"
                className="self-start"
                onClick={() => set({ ...draft, buyers: draft.buyers.filter((_, j) => j !== i) })}
              >
                Remove buyer {i + 1}
              </Button>
            )}
          </div>
        ))}
        {draft.buyers.length < MAX_BUYERS && (
          <Button
            className="self-start"
            onClick={() => set({ ...draft, buyers: [...draft.buyers, { label: "", keywords: "", seniorities: [] }] })}
          >
            Add a buyer
          </Button>
        )}
      </div>
      <TextField
        label="Titles that rule someone out"
        rows={3}
        value={draft.exclude}
        onChange={(exclude) => set({ ...draft, exclude })}
        hint="One per line, up to 20: recruiter on one line, student on the next."
      />
    </Card>
  );
}

function AddEventForm({ onAdd, busy }: { onAdd: (body: S["EventAdd"]) => Promise<boolean>; busy: boolean }) {
  const [name, setName] = useState("");
  const [day, setDay] = useState("");
  const [url, setUrl] = useState("");
  const dayId = useId();
  async function submit(e: FormEvent) {
    e.preventDefault();
    const added = await onAdd({ name: name.trim(), day: day || null, url: url.trim() || null });
    if (added) {
      // cleared once it's in the plan, so a second click can't add it again; kept as typed when it wasn't added
      setName("");
      setDay("");
      setUrl("");
    }
  }
  return (
    <form
      onSubmit={(e) => void submit(e)}
      className="flex flex-col gap-3 rounded-lg border border-dashed border-line p-3"
    >
      <h3 className="text-sm font-medium">Add an event you know</h3>
      <div className="grid gap-3 sm:grid-cols-3">
        <TextField label="Name" value={name} onChange={setName} />
        <label htmlFor={dayId} className="flex flex-col gap-1 text-sm">
          <span className="font-medium">Starts (optional)</span>
          <input id={dayId} type="date" className={field} value={day} onChange={(e) => setDay(e.target.value)} />
        </label>
        <TextField label="Web page (optional)" value={url} onChange={setUrl} />
      </div>
      <Button type="submit" className="self-start" disabled={busy || !name.trim()}>
        Add this event
      </Button>
    </form>
  );
}

function PlanEditor({ run, plan }: { run: EventRun; plan: EventPlan }) {
  const [draft, setDraft] = useState(() => draftOf(plan));
  const save = useSavePlan(run.id);
  const add = useAddEvent(run.id);
  const picked = draft.events.filter((e) => e.picked).length;
  const busy = save.isPending || add.isPending;

  /** The plan to send, or null after saying what to fix (the server's schema check would only say "something went
   * wrong"). */
  function checked(approve: boolean) {
    const body = bodyOf(draft, approve);
    const problem = planProblem(body);
    if (problem) {
      notify(problem, "error");
      return null;
    }
    return body;
  }

  function submit(approve: boolean) {
    const body = checked(approve);
    if (!body) return;
    save.mutate(body, {
      onSuccess: (saved) => {
        if (saved.plan) setDraft(draftOf(saved.plan));
        notify(approve ? "Searching: this page updates as it goes" : "Plan saved");
      },
    });
  }

  async function addEvent(body: S["EventAdd"]): Promise<boolean> {
    try {
      const typed = checked(false); // keep what's typed in the plan
      if (!typed) return false;
      await save.mutateAsync(typed);
      const added = await add.mutateAsync(body);
      if (added.plan) setDraft(draftOf(added.plan));
      notify("Event added");
      return true;
    } catch {
      return false; // the failed change has said why already (every failed change does, in queryClient.ts)
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <Card className="p-4 text-sm">
        <p className="text-[15px] font-semibold">{plan.company_name}</p>
        <p className="text-muted">{plan.offering}</p>
        <p className="mt-2 text-[13px] text-muted">
          Nothing is searched until you approve. Pick up to {plan.max_picked} events; each runs up to {plan.max_queries}{" "}
          LinkedIn searches, one per line.
        </p>
      </Card>
      {/* Locked while a save or an add is under way: its answer replaces the draft, so anything typed meanwhile
          would be lost. */}
      <fieldset disabled={busy} aria-busy={busy} className="flex min-w-0 flex-col gap-4">
        <IcpEditor draft={draft} set={setDraft} />
        <Card className="flex flex-col gap-3 p-4">
          <h2 className="text-[17px] font-semibold">
            Events{" "}
            <span className="text-sm font-normal text-muted">
              ({picked} of {plan.max_picked} picked)
            </span>
          </h2>
          {plan.events.length === 0 && (
            <p className="text-sm text-muted">No events were found. Add the ones you know.</p>
          )}
          <ul className="flex flex-col gap-3">
            {plan.events.map((event, i) => {
              const state = draft.events[i] ?? { picked: false, queries: "" };
              const link = safeUrl(event.url);
              const full = !state.picked && picked >= plan.max_picked;
              const setEvent = (change: Partial<typeof state>) =>
                setDraft({ ...draft, events: draft.events.map((e, j) => (j === i ? { ...e, ...change } : e)) });
              return (
                <li key={event.index} className="flex flex-col gap-2 rounded-lg border border-line p-3 text-sm">
                  <label className="flex items-start gap-2">
                    <input
                      type="checkbox"
                      className="mt-1"
                      checked={state.picked}
                      disabled={full}
                      onChange={(e) => setEvent({ picked: e.target.checked })}
                    />
                    <span className="min-w-0">
                      <span className="font-medium">Search {event.name}</span>
                      <span className="block text-[13px] text-muted">
                        {[when(event.start_date, event.end_date), event.location].filter(Boolean).join(" · ")}
                      </span>
                    </span>
                  </label>
                  <div className="flex flex-wrap gap-2">
                    {event.own && <Chip tone="accent">Added by you</Chip>}
                    {event.past && <Chip>Over: looks for people who went</Chip>}
                    {link && (
                      <a
                        className="inline-flex items-center gap-1 text-accent-ink hover:underline"
                        href={link}
                        target="_blank"
                        rel="noreferrer"
                      >
                        Event page <ExternalLink size={12} aria-hidden="true" />
                      </a>
                    )}
                  </div>
                  {event.why && <p className="text-muted">{event.why}</p>}
                  <details>
                    <summary className="cursor-pointer text-[13px] text-muted">
                      Searches ({lines(state.queries).length})
                    </summary>
                    <TextField
                      label={`LinkedIn searches for ${event.name}`}
                      rows={4}
                      value={state.queries}
                      onChange={(queries) => setEvent({ queries })}
                      hint="One per line."
                    />
                  </details>
                </li>
              );
            })}
          </ul>
          <AddEventForm onAdd={addEvent} busy={busy} />
        </Card>
      </fieldset>
      <div className="flex flex-wrap gap-2">
        <Button
          variant="primary"
          disabled={busy || picked === 0 || picked > plan.max_picked}
          onClick={() => submit(true)}
        >
          Find the people
        </Button>
        <Button disabled={busy} onClick={() => submit(false)}>
          Save the plan
        </Button>
      </div>
    </div>
  );
}

// ------------------------------------------------------------------------------------------------- progress
function Working({ run }: { run: EventRun }) {
  const progress = run.progress;
  return (
    <Card className="flex flex-col gap-4 p-4" aria-live="polite">
      {progress && (
        <ol className="flex flex-col gap-2 text-sm">
          {progress.steps.map((step, i) => (
            <li key={step} className="flex items-center gap-2">
              <span
                className={clsx(
                  "inline-flex size-5 items-center justify-center rounded-full text-[11px]",
                  i < progress.step
                    ? "bg-good-tint text-good"
                    : i === progress.step
                      ? "bg-accent-tint text-accent-ink"
                      : "bg-chip text-muted",
                )}
                aria-hidden="true"
              >
                {i < progress.step ? <Check size={12} /> : i + 1}
              </span>
              <span className={clsx(i === progress.step && "font-medium")}>
                {step}
                {i < progress.step ? " (done)" : i === progress.step ? " (under way)" : ""}
              </span>
            </li>
          ))}
        </ol>
      )}
      {progress?.note && <p className="text-sm text-warm">{progress.note}</p>}
      {run.found && (
        <div className="flex flex-col gap-2 text-sm">
          <div
            role="progressbar"
            aria-label="How far along the search is"
            aria-valuenow={run.found.percent}
            aria-valuemin={0}
            aria-valuemax={100}
            className="h-2 overflow-hidden rounded-full bg-chip"
          >
            <div className="h-full bg-accent" style={{ width: `${run.found.percent}%` }} />
          </div>
          <p className="text-muted">
            {run.found.posts} posts found · {run.found.people} people at the events · {run.found.emails} verified emails
          </p>
        </div>
      )}
    </Card>
  );
}

// ---------------------------------------------------------------------------------------------------- the list
function download(run: EventRun, leads: EventLead[]) {
  const blob = new Blob([toEventCsv(leads)], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `${run.company_name ?? run.domain} - event leads.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

const ATTENDANCE_TONE: Record<string, "warm" | "accent" | "good" | "neutral"> = {
  Speaking: "warm",
  Exhibiting: "accent",
  Going: "good",
  Went: "neutral",
};

function LeadCard({ lead }: { lead: EventLead }) {
  const profile = safeUrl(lead.linkedin);
  const post = safeUrl(lead.post);
  return (
    <li className="flex flex-col gap-1 px-4 py-3 text-sm">
      <p className="flex flex-wrap items-center gap-2">
        {profile ? (
          <a className="font-semibold text-accent-ink hover:underline" href={profile} target="_blank" rel="noreferrer">
            {lead.name}
          </a>
        ) : (
          <span className="font-semibold">{lead.name}</span>
        )}
        <Chip tone={ATTENDANCE_TONE[lead.attendance] ?? "neutral"}>{lead.attendance}</Chip>
        <span className="text-muted">ICP {lead.score}</span>
      </p>
      <p>
        {lead.title}
        {lead.company ? ` at ${lead.company}` : ""}
      </p>
      <p className="flex flex-wrap items-center gap-3 text-muted">
        {lead.email && (
          <a className="inline-flex items-center gap-1 hover:text-ink" href={`mailto:${lead.email}`}>
            <Mail size={12} aria-hidden="true" /> {lead.email}
          </a>
        )}
        <span>{lead.event}</span>
        {post && (
          <a className="inline-flex items-center gap-1 hover:text-ink" href={post} target="_blank" rel="noreferrer">
            Their post <ExternalLink size={12} aria-hidden="true" />
          </a>
        )}
      </p>
      {lead.reasons.length > 0 && <p className="text-[13px] text-muted">{lead.reasons.join("; ")}</p>}
    </li>
  );
}

function List({ run }: { run: EventRun }) {
  const leads = useEventLeads(run.id, run.status === "ready");
  if (run.status === "expired")
    return <EmptyState title="This list has expired">Its personal data has been deleted.</EmptyState>;
  if (leads.isPending) return <p className="text-sm text-muted">Loading the list…</p>;
  if (leads.isError) return <p className="text-sm text-bad">Couldn't load the list. {leads.error.message}</p>;
  if (!leads.data.length) return <EmptyState title="Nobody on the list">{run.detail}</EmptyState>;
  return (
    <Card>
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-4 py-3 text-sm">
        <p>
          {leads.data.length} lead{leads.data.length === 1 ? "" : "s"}, best fit first
          {run.expires ? <span className="text-muted"> · kept until {formatDateTimeDay(run.expires)}</span> : null}
        </p>
        <Button onClick={() => download(run, leads.data)}>
          <Download size={14} aria-hidden="true" /> Download CSV
        </Button>
      </div>
      <ul className="divide-y divide-line" aria-label="Leads">
        {leads.data.map((lead) => (
          <LeadCard key={`${lead.linkedin}-${lead.email}-${lead.name}`} lead={lead} />
        ))}
      </ul>
    </Card>
  );
}

// ------------------------------------------------------------------------------------------------------ page
export function EventRunPage() {
  const { runId = "" } = useParams();
  const run = useEventRun(runId);
  const cancel = useCancelEventRun(runId);
  if (run.isPending) return <p className="text-sm text-muted">Loading…</p>;
  if (run.isError)
    return (
      <div className="flex max-w-4xl flex-col gap-4">
        <Link to="/events" className="text-sm text-accent-ink hover:underline">
          ← Events
        </Link>
        <EmptyState title="Can't show this run">{run.error.message}</EmptyState>
      </div>
    );
  const r = run.data;
  const stopped = r.status === "failed" || r.status === "canceled";
  return (
    <div className="flex max-w-4xl flex-col gap-6">
      <Link to="/events" className="text-sm text-accent-ink hover:underline">
        ← Events
      </Link>
      <PageHeader eyebrow={r.company_name ? r.domain : "Events run"} title={r.company_name ?? r.domain}>
        <Chip tone={statusTone(r.status)}>{r.label}</Chip>
        {!FINISHED.has(r.status) && (
          <Button
            variant="quiet"
            disabled={cancel.isPending}
            onClick={() => {
              if (!window.confirm("Cancel this run? It stops before its next step and can't be restarted.")) return;
              cancel.mutate(undefined);
            }}
          >
            Cancel run
          </Button>
        )}
      </PageHeader>
      <p className="text-[13px] text-muted">
        {usd(r.spent_usd)} of {usd(r.budget_usd)} spent
        {r.company_id && (
          <>
            {" · "}
            <Link className="text-accent-ink hover:underline" to={`/companies/${r.company_id}`}>
              Open the company
            </Link>
          </>
        )}
      </p>
      {r.working && <Working run={r} />}
      {r.status === "awaiting_approval" && r.plan && <PlanEditor key={r.id} run={r} plan={r.plan} />}
      {(r.status === "ready" || r.status === "expired") && <List run={r} />}
      {stopped && (
        <Card className="p-4 text-sm">
          <p className="font-medium">{r.detail}</p>
          {r.error && <p className="mt-1 text-muted">Details: {r.error}</p>}
        </Card>
      )}
    </div>
  );
}
