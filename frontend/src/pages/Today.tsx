import { ArrowRight, Check, Flame, Sparkles, Trophy } from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";

import { type MoveCard, type S, useEnrichToday, usePull, useStats, useToday, useUpdatePerson } from "@/api/hooks";
import { CompanyCard } from "@/components/CompanyCard";
import { CompanyPanel } from "@/components/CompanyPanel";
import { MoveRow } from "@/components/MoveRow";
import { Button, Card, EmptyState, PageHeader } from "@/components/ui";
import { formatLongDay, relativeDay } from "@/lib/format";
import { safeUrl } from "@/lib/safe";

function greeting(): string {
  const hour = new Date().getHours();
  if (hour < 12) return "Good morning";
  if (hour < 18) return "Good afternoon";
  return "Good evening";
}

function Stat({ label, value, sub, icon }: { label: string; value: string; sub?: string; icon?: ReactNode }) {
  return (
    <Card className="flex flex-col gap-1 px-4 py-3.5">
      <span className="flex items-center gap-1.5 text-[13px] font-medium text-muted">
        {icon}
        {label}
      </span>
      <span className="text-[22px] font-bold tracking-tight">{value}</span>
      {sub && <span className="text-[13px] text-muted">{sub}</span>}
    </Card>
  );
}

function StatsRow({ dueCount }: { dueCount: number }) {
  const { data: s, isError } = useStats();
  if (isError)
    return (
      <p role="alert" className="rounded-card border border-line bg-surface px-4 py-3 text-sm text-muted">
        Couldn't load your progress. It'll show again when the page refreshes.
      </p>
    );
  if (!s) return <div className="h-[92px]" aria-hidden="true" />;
  const toNext = s.next_level_xp - s.xp;
  const progress = Math.round(((s.xp - s.level_floor_xp) / (s.next_level_xp - s.level_floor_xp)) * 100);
  return (
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
      <Stat
        label="Done today"
        value={`${s.today_moves}`}
        sub={dueCount ? `${dueCount} still to do` : "Nothing left today"}
      />
      <Stat
        label="Streak"
        icon={<Flame size={14} aria-hidden="true" />}
        value={`${s.streak} ${s.streak === 1 ? "day" : "days"}`}
        sub={`Best ${s.best_streak} · ${s.streak_min}+ moves a day`}
      />
      <Card className="flex flex-col gap-1 px-4 py-3.5">
        <span className="flex items-center gap-1.5 text-[13px] font-medium text-muted">
          <Trophy size={14} aria-hidden="true" />
          Level {s.level}
        </span>
        <span className="text-[22px] font-bold tracking-tight">{s.level_title}</span>
        <div
          className="mt-1 h-1.5 overflow-hidden rounded-full bg-chip"
          role="progressbar"
          aria-label="Progress to the next level"
          aria-valuenow={progress}
          aria-valuemin={0}
          aria-valuemax={100}
        >
          <div className="h-full rounded-full bg-accent" style={{ width: `${progress}%` }} />
        </div>
        <span className="text-[13px] text-muted">
          {s.xp} XP · {toNext} to level {s.level + 1}
        </span>
      </Card>
      <Stat
        label="Pipeline"
        value={`${s.funnel["replied"] ?? 0} replied`}
        sub={`${s.funnel["contacted"] ?? 0} contacted of ${s.in_play}${
          s.days_left !== null ? ` · ${s.days_left} days left` : ""
        }`}
      />
    </div>
  );
}

type Group = S["TodayGroup"];

/** Calls stay as rows; everything else is gathered by company, in the order the server ranked it. */
function arrange(groups: Group[]) {
  const calls = groups.find((g) => g.key === "calls")?.moves ?? [];
  const byCompany = new Map<string, MoveCard[]>();
  const loose: MoveCard[] = [];
  for (const g of groups) {
    if (g.key === "calls") continue;
    for (const m of g.moves) {
      if (!m.company_id) loose.push(m);
      else byCompany.set(m.company_id, [...(byCompany.get(m.company_id) ?? []), m]);
    }
  }
  return { calls, companies: [...byCompany.entries()], loose };
}

function LoomRow({ ask }: { ask: S["LoomAsk"] }) {
  const patch = useUpdatePerson();
  const linkedin = safeUrl(ask.person.linkedin);
  return (
    <div className="flex flex-wrap items-center justify-between gap-2 px-4 py-3 text-sm">
      <span className="min-w-0">
        <span className="font-semibold">{ask.person.name}</span>
        <span className="text-muted">
          {" "}
          · {ask.person.title}
          {ask.company && `, ${ask.company.name}`}
        </span>
      </span>
      <span className="flex items-center gap-1">
        {linkedin && (
          <a
            className="inline-flex min-h-[34px] items-center rounded-lg px-2.5 text-sm font-medium text-muted hover:bg-chip hover:text-ink"
            href={linkedin}
            target="_blank"
            rel="noreferrer"
          >
            LinkedIn
          </a>
        )}
        <Button
          variant="primary"
          disabled={patch.isPending}
          onClick={() => patch.mutate({ id: ask.person.id, loom: "sent" })}
        >
          <Check size={14} aria-hidden="true" />
          Loom sent
        </Button>
      </span>
    </div>
  );
}

export function TodayPage() {
  const { data, isPending, isError } = useToday();
  const pull = usePull();
  const [open, setOpen] = useState<string | null>(null);
  const enrich = useEnrichToday();
  const asked = useRef(false);
  useEffect(() => {
    if (!asked.current) {
      asked.current = true; // get today's companies' emails ready before they're opened
      enrich.mutate(undefined);
    }
  }, [enrich]);
  if (isPending) return <p className="text-sm text-muted">Loading today…</p>;
  if (isError) return <EmptyState title="Couldn't load today">Reload the page to try again.</EmptyState>;

  const due = data.groups.reduce((n, g) => n + g.moves.length, 0);
  const { calls, companies, loose } = arrange(data.groups);
  const title = companies.length
    ? `${greeting()}. ${companies.length} ${companies.length === 1 ? "company" : "companies"} today.`
    : due
      ? `${greeting()}. ${due} ${due === 1 ? "thing" : "things"} today.`
      : `${greeting()}. You're clear.`;
  return (
    <div className="flex max-w-6xl flex-col gap-6">
      <PageHeader eyebrow={formatLongDay(data.today)} title={title} />

      <StatsRow dueCount={due} />

      {calls.length > 0 && (
        <section aria-labelledby="g-calls" className="flex flex-col gap-2">
          <h2 id="g-calls" className="text-[15px] font-semibold">
            Interviews and calls
          </h2>
          <Card className="divide-y divide-line-soft">
            {calls.map((m) => (
              <MoveRow key={m.id} move={m} today={data.today} />
            ))}
          </Card>
        </section>
      )}

      {data.looms.length > 0 && (
        <section aria-labelledby="g-looms" className="flex flex-col gap-2">
          <div className="flex items-baseline justify-between">
            <h2 id="g-looms" className="text-[15px] font-semibold">
              Loom requests
            </h2>
            <span className="text-[13px] text-muted">{data.looms.length}</span>
          </div>
          <Card className="divide-y divide-line-soft">
            {data.looms.map((a) => (
              <LoomRow key={a.person.id} ask={a} />
            ))}
          </Card>
        </section>
      )}

      {due === 0 && data.more > 0 ? (
        <EmptyState title="Done for today. Nice work.">
          <p>That's enough for one day. The rest will be here tomorrow.</p>
        </EmptyState>
      ) : due === 0 ? (
        <EmptyState title="Nothing left for today">
          <p>Get ahead on tomorrow, or plan the week.</p>
          <div className="mt-4 flex justify-center gap-2">
            <Button variant="primary" disabled={pull.isPending} onClick={() => pull.mutate(3)}>
              <Sparkles size={14} aria-hidden="true" />
              Pull 3 moves forward
            </Button>
            <Link
              to="/plan"
              className="inline-flex min-h-[38px] items-center gap-1.5 rounded-lg px-3 text-sm font-medium text-muted hover:bg-chip hover:text-ink"
            >
              See the plan <ArrowRight size={14} aria-hidden="true" />
            </Link>
          </div>
        </EmptyState>
      ) : (
        <>
          {companies.length > 0 && (
            <section aria-labelledby="g-companies" className="flex flex-col gap-2">
              <div className="flex items-baseline justify-between">
                <h2 id="g-companies" className="text-[15px] font-semibold">
                  Companies
                </h2>
                <span className="text-[13px] text-muted">Click one to see it and reach its people</span>
              </div>
              <Card className="divide-y divide-line-soft">
                {companies.map(([id, moves]) => (
                  <CompanyCard key={id} moves={moves} onOpen={() => setOpen(id)} />
                ))}
              </Card>
            </section>
          )}
          {loose.length > 0 && (
            <section aria-labelledby="g-other" className="flex flex-col gap-2">
              <h2 id="g-other" className="text-[15px] font-semibold">
                Other
              </h2>
              <Card className="divide-y divide-line-soft">
                {loose.map((m) => (
                  <MoveRow key={m.id} move={m} today={data.today} />
                ))}
              </Card>
            </section>
          )}
        </>
      )}

      {open && <CompanyPanel id={open} onClose={() => setOpen(null)} />}

      <div className="grid gap-6 lg:grid-cols-2">
        <section aria-labelledby="waiting" className="flex flex-col gap-2">
          <div className="flex items-baseline justify-between">
            <h2 id="waiting" className="text-[15px] font-semibold">
              Waiting on a reply
            </h2>
            <span className="text-[13px] text-muted">{data.waiting_total}</span>
          </div>
          {data.waiting.length ? (
            <Card className="divide-y divide-line-soft">
              {data.waiting.map((m) => (
                <div key={m.id} className="flex items-center justify-between gap-3 px-4 py-3 text-sm">
                  <span className="min-w-0 truncate">
                    <span className="font-semibold">{m.person?.name}</span>
                    {m.company && (
                      <Link to={`/companies/${m.company.id}`} className="text-muted hover:text-ink">
                        {" "}
                        · {m.company.name}
                      </Link>
                    )}
                  </span>
                  <span className="shrink-0 text-[13px] text-muted">
                    {m.status === "open"
                      ? `${m.sequence?.next === "dm" ? "Message" : "Bump"} ${relativeDay(m.due, data.today)}`
                      : "Sent"}
                  </span>
                </div>
              ))}
            </Card>
          ) : (
            <EmptyState title="No one yet">People you've reached show up here until they reply.</EmptyState>
          )}
        </section>
        <section aria-labelledby="done" className="flex flex-col gap-2">
          <div className="flex items-baseline justify-between">
            <h2 id="done" className="text-[15px] font-semibold">
              Done today
            </h2>
            <span className="text-[13px] text-muted">{data.done_today.length}</span>
          </div>
          {data.done_today.length ? (
            <Card className="divide-y divide-line-soft">
              {data.done_today.map((m) => (
                <MoveRow key={m.id} move={m} today={data.today} compact />
              ))}
            </Card>
          ) : (
            <EmptyState title="Nothing yet">Each move you finish lands here.</EmptyState>
          )}
        </section>
      </div>
    </div>
  );
}
