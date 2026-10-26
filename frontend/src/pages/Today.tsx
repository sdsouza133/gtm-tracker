import { ArrowRight, Flame, Sparkles, Trophy } from "lucide-react";
import type { ReactNode } from "react";
import { Link } from "react-router-dom";

import { usePull, useStats, useToday } from "@/api/hooks";
import { MoveRow } from "@/components/MoveRow";
import { Button, Card, EmptyState, PageHeader } from "@/components/ui";
import { formatLongDay, relativeDay } from "@/lib/format";

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
  const { data: s } = useStats();
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

export function TodayPage() {
  const { data, isPending, isError } = useToday();
  const pull = usePull();
  if (isPending) return <p className="text-sm text-muted">Loading today…</p>;
  if (isError) return <EmptyState title="Couldn't load today">Reload the page to try again.</EmptyState>;

  const due = data.groups.reduce((n, g) => n + g.moves.length, 0);
  return (
    <div className="flex max-w-6xl flex-col gap-6">
      <PageHeader
        eyebrow={formatLongDay(data.today)}
        title={due ? `${greeting()}. ${due} ${due === 1 ? "move" : "moves"} today.` : `${greeting()}. You're clear.`}
      >
        {data.overdue > 0 && <span className="text-sm font-medium text-bad">{data.overdue} overdue</span>}
      </PageHeader>

      <StatsRow dueCount={due} />

      {data.groups.length === 0 ? (
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
        data.groups.map((group) => (
          <section key={group.key} aria-labelledby={`g-${group.key}`} className="flex flex-col gap-2">
            <div className="flex items-baseline justify-between">
              <h2 id={`g-${group.key}`} className="text-[15px] font-semibold">
                {group.label}
              </h2>
              <span className="text-[13px] text-muted">{group.moves.length} left</span>
            </div>
            <Card className="divide-y divide-line-soft">
              {group.moves.map((m) => (
                <MoveRow key={m.id} move={m} today={data.today} />
              ))}
            </Card>
          </section>
        ))
      )}

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
