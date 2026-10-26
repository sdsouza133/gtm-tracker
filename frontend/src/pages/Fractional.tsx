import { clsx } from "clsx";
import { Flame, Linkedin, Minus, Plus, Search, Trophy } from "lucide-react";
import { useDeferredValue, useState, type ReactNode } from "react";
import { useSearchParams } from "react-router-dom";

import {
  type FxShow,
  type ProspectCard,
  useFxBoard,
  useFxPipeline,
  useFxProspects,
  useSettings,
  useUpdateProspect,
  useUpdateSettings,
} from "@/api/hooks";
import { ProspectDrawer } from "@/components/ProspectDrawer";
import { Button, Card, Chip, EmptyState, PageHeader } from "@/components/ui";
import { formatDay, formatLongDay, initials, nextWorkday } from "@/lib/format";

type View = "today" | "pipeline" | "all";
const VIEWS: [View, string][] = [
  ["today", "Today"],
  ["pipeline", "Pipeline"],
  ["all", "All companies"],
];
const STAGE_LABEL: Record<string, string> = {
  untouched: "Not reached",
  waiting: "Waiting",
  talking: "Talking",
  call: "Call booked",
  proposal: "Proposal",
  won: "Client",
  closed: "Closed",
};
const MAX_GOAL = 30;

function Section({
  title,
  hint,
  count,
  children,
}: {
  title: string;
  hint?: string;
  count?: number;
  children: ReactNode;
}) {
  return (
    <section aria-label={title} className="flex flex-col gap-2">
      <div className="flex items-baseline justify-between gap-3">
        <h2 className="text-[15px] font-semibold">{title}</h2>
        {count !== undefined && <span className="text-[13px] text-muted">{count}</span>}
      </div>
      {hint && <p className="-mt-1 text-[13px] text-muted">{hint}</p>}
      {children}
    </section>
  );
}

function ProspectTile({ p, today, onOpen }: { p: ProspectCard; today: string; onOpen: (id: string) => void }) {
  const update = useUpdateProspect();
  const reached = p.first_touch !== null;
  return (
    <Card className="flex flex-col gap-2.5 p-4">
      <div className="flex items-start gap-3">
        <span
          className={clsx(
            "flex h-7 w-7 shrink-0 items-center justify-center rounded-lg text-[13px] font-semibold",
            reached ? "bg-good-tint text-good" : "bg-chip text-body",
          )}
        >
          {reached ? "✓" : p.rank}
        </span>
        <div className="min-w-0 flex-1">
          <button
            type="button"
            onClick={() => onOpen(p.id)}
            className="text-left text-[15px] font-semibold hover:underline"
          >
            {p.name}
          </button>
          <div className="mt-1 flex flex-wrap gap-1.5">
            {p.round && <Chip>{p.round}</Chip>}
            {p.hq && <Chip>{p.hq}</Chip>}
            {p.employees && <Chip>{p.employees} people</Chip>}
            {(!p.dmarc || p.dmarc === "none" || p.dmarc === "missing") && <Chip tone="warm">No DMARC</Chip>}
          </div>
        </div>
        <Chip tone="accent">{p.xp} XP</Chip>
      </div>
      {p.one_liner && <p className="text-sm text-body">{p.one_liner}</p>}
      {p.why_now && (
        <p className="text-[13px] text-muted">
          <span className="font-semibold text-body">Why now: </span>
          {p.why_now}
        </p>
      )}
      <div className="flex flex-wrap gap-1.5">
        {p.people.map((person) => {
          const touched = p.touched.includes(person.key);
          const label = (
            <>
              <span aria-hidden="true" className="font-semibold">
                {initials(person.name)}
              </span>
              {person.name.replace(/\s*\(.*\)/, "")}
              {person.title && <span className="text-muted"> · {person.title.split(/[,|]/)[0]}</span>}
            </>
          );
          const style = clsx(
            "inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[12px]",
            touched ? "bg-good-tint text-good" : "bg-chip text-body",
          );
          return person.linkedin ? (
            <a key={person.key} href={person.linkedin} target="_blank" rel="noreferrer" className={style}>
              <Linkedin size={11} aria-hidden="true" />
              {label}
            </a>
          ) : (
            <span key={person.key} className={style}>
              {label}
            </span>
          );
        })}
      </div>
      <div className="flex flex-wrap items-center justify-between gap-2 border-t border-line-soft pt-2.5">
        <span className="text-[13px] text-muted">Next: {p.next_step}</span>
        <div className="flex gap-1.5">
          {p.stage === "untouched" && p.status === "open" && p.effective_day <= today && (
            <Button
              variant="quiet"
              disabled={update.isPending}
              onClick={() => update.mutate({ id: p.id, day_override: nextWorkday(today) })}
            >
              Tomorrow
            </Button>
          )}
          <Button onClick={() => onOpen(p.id)}>Open dossier</Button>
        </div>
      </div>
    </Card>
  );
}

function Hero() {
  const { data: b } = useFxBoard();
  const { data: settings } = useSettings();
  const save = useUpdateSettings();
  if (!b) return null;
  const s = b.stats;
  const goal = b.goal;
  const done = goal === 0 || b.hits_today >= goal;
  const pct = goal === 0 ? 100 : Math.min(100, Math.round((b.hits_today / goal) * 100));
  const setGoal = (n: number) =>
    save.mutate({ fx_goals: { ...(settings?.fx_goals ?? {}), [b.today]: Math.max(0, Math.min(MAX_GOAL, n)) } });
  const toNext = s.level.next_xp === null ? null : s.level.next_xp - s.xp;
  return (
    <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
      <Card className="flex flex-col gap-2 p-4">
        <span className="text-[13px] font-medium text-muted">Today's goal</span>
        <span className="text-[26px] font-bold tracking-tight">
          {b.hits_today}/{goal}
        </span>
        <div
          className="h-1.5 overflow-hidden rounded-full bg-chip"
          role="progressbar"
          aria-label="Today's goal"
          aria-valuenow={pct}
          aria-valuemin={0}
          aria-valuemax={100}
        >
          <div className={clsx("h-full rounded-full", done ? "bg-good" : "bg-accent")} style={{ width: `${pct}%` }} />
        </div>
        <span className="text-[13px] text-muted">
          {goal === 0
            ? "No goal today. Rest or get ahead."
            : done
              ? "Goal hit. The rest is bonus."
              : `${goal - b.hits_today} to go`}
        </span>
        <div className="flex items-center gap-2">
          <Button
            variant="quiet"
            aria-label="Lower today's goal"
            disabled={save.isPending || goal === 0}
            onClick={() => setGoal(goal - 1)}
          >
            <Minus size={14} aria-hidden="true" />
          </Button>
          <span className="text-[13px] text-muted">{goal} / day</span>
          <Button
            variant="quiet"
            aria-label="Raise today's goal"
            disabled={save.isPending || goal >= MAX_GOAL}
            onClick={() => setGoal(goal + 1)}
          >
            <Plus size={14} aria-hidden="true" />
          </Button>
        </div>
      </Card>
      <Card className="flex flex-col gap-2 p-4">
        <span className="flex items-center gap-1.5 text-[13px] font-medium text-muted">
          <Flame size={14} aria-hidden="true" /> Streak
        </span>
        <span className="text-[26px] font-bold tracking-tight">
          {s.streak} <span className="text-sm font-medium text-muted">days · best {s.best_streak}</span>
        </span>
        <div className="grid grid-cols-5 gap-1" aria-label="Hits over the last four weeks">
          {s.heat.map((d) => {
            const level =
              d.day > b.today
                ? "future"
                : d.hits === 0
                  ? "none"
                  : d.goal && d.hits >= d.goal
                    ? "l3"
                    : d.goal && d.hits >= d.goal / 2
                      ? "l2"
                      : "l1";
            return (
              <span
                key={d.day}
                title={`${formatLongDay(d.day)}: ${d.hits} of ${d.goal}`}
                className={clsx(
                  "h-4 rounded",
                  level === "future" && "bg-line-soft",
                  level === "none" && "bg-chip",
                  level === "l1" && "bg-accent/30",
                  level === "l2" && "bg-accent/60",
                  level === "l3" && "bg-accent",
                  d.day === b.today && "ring-2 ring-ink",
                )}
              />
            );
          })}
        </div>
        <span className="text-[12px] text-muted">Weekdays where you hit the goal. Weekends don't break it.</span>
      </Card>
      <Card className="flex flex-col gap-2 p-4">
        <span className="flex items-center gap-1.5 text-[13px] font-medium text-muted">
          <Trophy size={14} aria-hidden="true" /> Level {s.level.number}
        </span>
        <span className="text-[22px] font-bold tracking-tight">{s.level.name}</span>
        <span className="text-[13px] text-muted">
          {s.xp} XP
          {toNext !== null && s.level.next_name ? ` · ${toNext} to ${s.level.next_name}` : " · max level"}
        </span>
        <span className="text-[12px] text-muted">A reply is worth 10, a call 25, a client 100.</span>
      </Card>
      <Card className="flex flex-col gap-2 p-4">
        <span className="text-[13px] font-medium text-muted">Fractional revenue</span>
        <span className="text-[26px] font-bold tracking-tight">${s.monthly_revenue.toLocaleString()}</span>
        <span className="text-[13px] text-muted">
          a month of ${s.revenue_goal.toLocaleString()} ({s.clients} client{s.clients === 1 ? "" : "s"})
        </span>
        <dl className="grid grid-cols-5 gap-1 text-center">
          {(["reached", "replied", "call", "proposal", "clients"] as const).map((k) => (
            <div key={k}>
              <dd className="text-sm font-semibold">{s.funnel[k] ?? 0}</dd>
              <dt className="text-[11px] text-muted">{k === "call" ? "calls" : k === "proposal" ? "proposals" : k}</dt>
            </div>
          ))}
        </dl>
      </Card>
    </div>
  );
}

function TodayView({ onOpen }: { onOpen: (id: string) => void }) {
  const { data: b, isPending, isError } = useFxBoard();
  const update = useUpdateProspect();
  if (isPending) return <p className="text-sm text-muted">Loading your list…</p>;
  if (isError) return <EmptyState title="Couldn't load your list">Reload the page to try again.</EmptyState>;
  const grid = "grid gap-3 lg:grid-cols-2";
  const next = b.coming_up[0];
  return (
    <div className="flex flex-col gap-6">
      <Hero />
      {b.follow_ups_due.length > 0 && (
        <Section
          title="Follow-ups due"
          count={b.follow_ups_due.length}
          hint={`Do these first: most replies come from the follow-up.${b.follow_ups_later ? ` ${b.follow_ups_later} more coming up.` : ""}`}
        >
          <Card className="divide-y divide-line-soft">
            {b.follow_ups_due.map((p) => (
              <div key={p.id} className="flex flex-wrap items-center gap-3 px-4 py-3">
                <button type="button" className="font-semibold hover:underline" onClick={() => onOpen(p.id)}>
                  {p.name}
                </button>
                <span className="flex-1 text-[13px] text-muted">
                  {p.next_step}
                  {p.first_touch && ` · first message ${formatDay(p.first_touch)}`}
                </span>
                {p.follow_up && (
                  <Button
                    variant="primary"
                    disabled={update.isPending}
                    onClick={() =>
                      update.mutate({ id: p.id, step: { name: p.follow_up?.step === "fu2" ? "fu2" : "fu1", on: true } })
                    }
                  >
                    Mark sent
                  </Button>
                )}
              </div>
            ))}
          </Card>
        </Section>
      )}
      {b.carried_over.length > 0 && (
        <Section
          title="Carried over"
          count={b.carried_over.length}
          hint="Not reached yet from earlier days. They count toward today."
        >
          <div className={grid}>
            {b.carried_over.map((p) => (
              <ProspectTile key={p.id} p={p} today={b.today} onOpen={onOpen} />
            ))}
          </div>
        </Section>
      )}
      <Section
        title={`Today's list · ${formatLongDay(b.today)}`}
        count={b.todays_list.length}
        hint="Ranked by fit. Read the dossier, then reach out."
      >
        {b.todays_list.length ? (
          <div className={grid}>
            {b.todays_list.map((p) => (
              <ProspectTile key={p.id} p={p} today={b.today} onOpen={onOpen} />
            ))}
          </div>
        ) : (
          <EmptyState title={b.carried_over.length ? "Nothing new today" : "Nothing left for today"}>
            {next && (
              <Button
                className="mt-3"
                disabled={update.isPending}
                onClick={() => update.mutate({ id: next.id, day_override: b.today })}
              >
                Pull {next.name} in from {formatDay(next.effective_day)}
              </Button>
            )}
          </EmptyState>
        )}
      </Section>
      {b.reached_today.length > 0 && (
        <Section
          title="Reached today"
          count={b.reached_today.length}
          hint="Nice. Follow-ups show up above when they're due."
        >
          <div className={grid}>
            {b.reached_today.map((p) => (
              <ProspectTile key={p.id} p={p} today={b.today} onOpen={onOpen} />
            ))}
          </div>
        </Section>
      )}
      {b.coming_up.length > 0 && (
        <Section title="Coming up" count={b.coming_up_total} hint="Research is ready if you want a head start.">
          <Card className="divide-y divide-line-soft">
            {b.coming_up.map((p) => (
              <div key={p.id} className="flex flex-wrap items-center gap-3 px-4 py-3">
                <button type="button" className="font-semibold hover:underline" onClick={() => onOpen(p.id)}>
                  {p.name}
                </button>
                <span className="min-w-0 flex-1 truncate text-[13px] text-muted">
                  {formatLongDay(p.effective_day)} · #{p.rank} · {p.one_liner}
                </span>
                <Button
                  variant="quiet"
                  disabled={update.isPending}
                  onClick={() => update.mutate({ id: p.id, day_override: b.today })}
                >
                  Do it today
                </Button>
              </div>
            ))}
          </Card>
        </Section>
      )}
      <Section title="Badges" count={b.stats.badges.filter((x) => x.earned).length}>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4">
          {b.stats.badges.map((badge) => (
            <div
              key={badge.key}
              className={clsx(
                "rounded-xl border p-3",
                badge.earned ? "border-accent bg-accent-tint" : "border-line opacity-60",
              )}
            >
              <p className="text-sm font-semibold">{badge.name}</p>
              <p className="text-[12px] text-muted">{badge.description}</p>
              <span className="sr-only">{badge.earned ? "Earned" : "Not earned yet"}</span>
            </div>
          ))}
        </div>
      </Section>
    </div>
  );
}

function PipelineView({ onOpen }: { onOpen: (id: string) => void }) {
  const { data, isPending, isError } = useFxPipeline();
  if (isPending) return <p className="text-sm text-muted">Loading the pipeline…</p>;
  if (isError) return <EmptyState title="Couldn't load the pipeline">Reload the page to try again.</EmptyState>;
  return (
    <div className="-mx-4 flex gap-3 overflow-x-auto px-4 pb-4 md:-mx-8 md:px-8">
      {data.map((col) => (
        <section
          key={col.key}
          aria-label={col.label}
          className="flex w-64 shrink-0 flex-col gap-2 rounded-card bg-[#EFEFF2] p-2.5"
        >
          <h2 className="flex justify-between px-1 text-[13px] font-semibold text-body">
            {col.label}
            <span className="rounded-md bg-surface px-1.5 text-[12px] font-medium text-muted">{col.total}</span>
          </h2>
          {col.items.map((p) => (
            <button
              key={p.id}
              type="button"
              onClick={() => onOpen(p.id)}
              className="rounded-xl border border-line bg-surface p-3 text-left shadow-sm hover:border-accent"
            >
              <span className="block text-sm font-semibold">{p.name}</span>
              <span className="text-[12px] text-muted">{p.next_step}</span>
            </button>
          ))}
          {col.total > col.items.length && (
            <p className="px-1 text-[12px] text-muted">+{col.total - col.items.length} more in All companies</p>
          )}
          {col.total === 0 && <p className="px-1 py-4 text-center text-[12px] text-muted">None yet.</p>}
        </section>
      ))}
    </div>
  );
}

function AllView({ onOpen }: { onOpen: (id: string) => void }) {
  const [q, setQ] = useState("");
  const [show, setShow] = useState<FxShow>("all");
  const [offset, setOffset] = useState(0);
  const query = useDeferredValue(q.trim());
  const { data, isPending, isError } = useFxProspects({ q: query || undefined, show, offset });
  const PAGE = 100;
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap gap-2">
        <label className="relative">
          <span className="sr-only">Search prospects</span>
          <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-field" aria-hidden="true" />
          <input
            type="search"
            className="min-h-[38px] w-72 rounded-lg border border-line bg-surface pl-9 pr-3 text-sm"
            placeholder="Company, person or what they do"
            value={q}
            onChange={(e) => {
              setQ(e.target.value);
              setOffset(0);
            }}
          />
        </label>
        <select
          aria-label="Show"
          className="min-h-[38px] rounded-lg border border-line bg-surface px-3 text-sm"
          value={show}
          onChange={(e) => {
            setShow(e.target.value as FxShow);
            setOffset(0);
          }}
        >
          <option value="all">Everything</option>
          <option value="untouched">Not reached yet</option>
          <option value="in_play">In play</option>
          <option value="closed">Clients, skipped and lost</option>
        </select>
      </div>
      {isPending ? (
        <p className="text-sm text-muted">Loading…</p>
      ) : isError ? (
        <EmptyState title="Couldn't load the list">Reload the page to try again.</EmptyState>
      ) : data.items.length === 0 ? (
        <EmptyState title="No companies match" />
      ) : (
        <Card className="divide-y divide-line-soft">
          {data.items.map((p) => (
            <button
              key={p.id}
              type="button"
              onClick={() => onOpen(p.id)}
              className="flex w-full flex-wrap items-center gap-3 px-4 py-3 text-left hover:bg-canvas"
            >
              <span className="w-6 text-[13px] text-muted">{p.rank}</span>
              <span className="font-semibold">{p.name}</span>
              <span className="min-w-0 flex-1 truncate text-[13px] text-muted">
                {formatDay(p.effective_day)} · {[p.round, p.hq, p.next_step].filter(Boolean).join(" · ")}
              </span>
              <Chip tone={p.stage === "won" ? "good" : p.stage === "untouched" ? "neutral" : "accent"}>
                {STAGE_LABEL[p.stage] ?? p.stage}
              </Chip>
            </button>
          ))}
        </Card>
      )}
      {data && data.total > PAGE && (
        <div className="flex items-center justify-between text-sm text-muted">
          <span>
            {offset + 1}–{Math.min(offset + PAGE, data.total)} of {data.total}
          </span>
          <div className="flex gap-2">
            <Button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>
              Previous
            </Button>
            <Button disabled={offset + PAGE >= data.total} onClick={() => setOffset(offset + PAGE)}>
              Next
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}

export function FractionalPage() {
  const [params, setParams] = useSearchParams();
  const view = (params.get("view") as View | null) ?? "today";
  const open = params.get("open");
  const { data: board } = useFxBoard();
  const today = board?.today ?? new Date().toISOString().slice(0, 10);
  const set = (key: string, value: string | null) =>
    setParams((p) => {
      const next = new URLSearchParams(p);
      if (value === null) next.delete(key);
      else next.set(key, value);
      return next;
    });

  return (
    <div className="flex max-w-6xl flex-col gap-5">
      <PageHeader title="Fractional" eyebrow="Outreach to funded startups">
        <div role="tablist" aria-label="Views" className="flex gap-1 rounded-lg bg-chip p-1">
          {VIEWS.map(([key, label]) => (
            <button
              key={key}
              type="button"
              role="tab"
              aria-selected={view === key}
              onClick={() => set("view", key)}
              className={clsx(
                "min-h-[32px] rounded-md px-3 text-sm font-medium",
                view === key ? "bg-surface text-ink shadow-sm" : "text-muted hover:text-ink",
              )}
            >
              {label}
            </button>
          ))}
        </div>
      </PageHeader>
      {view === "today" && <TodayView onOpen={(id) => set("open", id)} />}
      {view === "pipeline" && <PipelineView onOpen={(id) => set("open", id)} />}
      {view === "all" && <AllView onOpen={(id) => set("open", id)} />}
      {open && <ProspectDrawer id={open} today={today} onClose={() => set("open", null)} />}
    </div>
  );
}
