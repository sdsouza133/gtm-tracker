import { clsx } from "clsx";
import { ChevronRight, Heart, Linkedin, Mail } from "lucide-react";

import type { MoveCard } from "@/api/hooks";
import { Chip } from "@/components/ui";
import { formatDay } from "@/lib/format";

function sent(m: MoveCard, step: "email" | "request"): boolean {
  const day = m.sequence?.steps?.[step];
  return typeof day === "string" && day !== "";
}

function Tick({ done, label, icon }: { done: boolean; label: string; icon: React.ReactNode }) {
  return (
    <span
      className={clsx(
        "inline-flex h-6 w-6 items-center justify-center rounded-full",
        done ? "bg-good-tint text-good" : "bg-chip text-muted",
      )}
      title={`${label}${done ? " sent" : " to send"}`}
      aria-label={`${label}${done ? " sent" : " to send"}`}
    >
      {icon}
    </span>
  );
}

/** One company on Today: the role, and each person with an email tick and a LinkedIn tick. Opens the company panel. */
export function CompanyCard({ moves, onOpen }: { moves: MoveCard[]; onOpen: () => void }) {
  const company = moves[0]?.company;
  if (!company) return null;
  const reach = moves.filter((m) => m.type === "reach" && m.person);
  const apply = moves.some((m) => m.type === "apply");
  const other = moves.filter((m) => m.type !== "reach" && m.type !== "apply");
  const total = reach.length * 2;
  const done = reach.reduce((n, m) => n + Number(sent(m, "email")) + Number(sent(m, "request")), 0);

  return (
    <button
      type="button"
      onClick={onOpen}
      className="flex w-full flex-col gap-3 px-4 py-3.5 text-left hover:bg-chip/50 focus-visible:bg-chip/50"
    >
      <div className="flex w-full items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="flex items-center gap-1.5 text-[15px] font-semibold text-ink">
            {company.loved && <Heart size={14} className="fill-current text-bad" aria-label="You love this job" />}
            {company.name}
          </p>
          {company.open_role && <p className="text-[13px] text-muted">{company.open_role}</p>}
          {company.posted && <p className="text-[12px] text-muted">Posted {formatDay(company.posted)}</p>}
        </div>
        <div className="flex shrink-0 items-center gap-1.5">
          {company.score ? <Chip tone="accent">Score {company.score.toFixed(1)}</Chip> : null}
          {apply && <Chip tone="warm">Apply</Chip>}
          <ChevronRight size={16} className="text-muted" aria-hidden="true" />
        </div>
      </div>
      {reach.length > 0 && (
        <div className="flex w-full flex-col gap-1.5">
          {reach.map((m) => (
            <div key={m.id} className="flex items-center justify-between gap-3 text-sm">
              <span className="min-w-0 truncate">
                {m.person?.name}
                <span className="text-muted"> · {m.person?.title}</span>
              </span>
              <span className="flex shrink-0 gap-1">
                <Tick done={sent(m, "email")} label="Email" icon={<Mail size={13} aria-hidden="true" />} />
                <Tick done={sent(m, "request")} label="LinkedIn" icon={<Linkedin size={13} aria-hidden="true" />} />
              </span>
            </div>
          ))}
          <p className="text-[13px] text-muted">
            {done} of {total} sent
          </p>
        </div>
      )}
      {other.length > 0 && <p className="text-[13px] text-muted">{other.map((m) => m.title).join(" · ")}</p>}
    </button>
  );
}
