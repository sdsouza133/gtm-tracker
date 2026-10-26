import { useState } from "react";

import { useActivity, usePlan, useServerToday } from "@/api/hooks";
import { MoveRow } from "@/components/MoveRow";
import { Button, Card, EmptyState, PageHeader } from "@/components/ui";
import { formatDateTimeDay, formatLongDay, formatTime } from "@/lib/format";

function History() {
  const [pages, setPages] = useState<(number | undefined)[]>([undefined]);
  return (
    <section aria-labelledby="history" className="flex flex-col gap-2">
      <h2 id="history" className="text-[15px] font-semibold">
        History
      </h2>
      <Card className="divide-y divide-line-soft">
        {pages.map((before, i) => (
          <HistoryPage
            key={before ?? 0}
            before={before}
            last={i === pages.length - 1}
            onMore={(id) => setPages([...pages, id])}
          />
        ))}
      </Card>
    </section>
  );
}

function HistoryPage({ before, last, onMore }: { before?: number; last: boolean; onMore: (id: number) => void }) {
  const { data, isPending } = useActivity(before);
  if (isPending) return <p className="px-4 py-3 text-sm text-muted">Loading…</p>;
  if (!data) return null;
  const items = data.items;
  const more = data.total > items.length;
  return (
    <>
      {items.map((a) => (
        <div key={a.id} className="flex items-baseline justify-between gap-4 px-4 py-2.5 text-sm">
          <span className="text-body">{a.text}</span>
          <span className="shrink-0 text-[13px] text-muted">
            {a.xp > 0 && <span className="mr-2 font-semibold text-good">+{a.xp} XP</span>}
            {formatDateTimeDay(a.at)} · {formatTime(a.at)}
          </span>
        </div>
      ))}
      {last && more && (
        <div className="px-4 py-3">
          <Button variant="quiet" onClick={() => onMore(items[items.length - 1]?.id ?? 0)}>
            Load older
          </Button>
        </div>
      )}
    </>
  );
}

export function PlanPage() {
  const { data, isPending, isError } = usePlan();
  const today = useServerToday();
  return (
    <div className="flex max-w-6xl flex-col gap-6">
      <PageHeader title="Plan" eyebrow="The next two weeks" />
      {isPending ? (
        <p className="text-sm text-muted">Loading the plan…</p>
      ) : isError ? (
        <EmptyState title="Couldn't load the plan">Reload the page to try again.</EmptyState>
      ) : data.length === 0 ? (
        <EmptyState title="Nothing planned">
          Add moves on a company page, or promote a company off the bench.
        </EmptyState>
      ) : (
        data.map((day) => (
          <section key={day.day} aria-label={formatLongDay(day.day)} className="flex flex-col gap-2">
            <h2 className="flex items-baseline justify-between text-[15px] font-semibold">
              {day.day === today ? "Today" : formatLongDay(day.day)}
              <span className="text-[13px] font-normal text-muted">{day.moves.length}</span>
            </h2>
            <Card className="divide-y divide-line-soft">
              {day.moves.map((m) => (
                <MoveRow key={m.id} move={m} today={today} compact />
              ))}
            </Card>
          </section>
        ))
      )}
      <History />
    </div>
  );
}
