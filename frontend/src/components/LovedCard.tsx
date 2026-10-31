import { clsx } from "clsx";
import { Check, ChevronRight, Heart, Linkedin, Mail } from "lucide-react";

import type { S } from "@/api/hooks";
import { Chip } from "@/components/ui";
import { formatDay, relativeDay } from "@/lib/format";

type Loved = S["LovedCompany"];
type LovedPerson = S["LovedPerson"];

/** A sent touch shows its day, one that can't happen says so, and one still to do stays empty. */
function Touch({
  label,
  day,
  icon,
  missing,
}: {
  label: string;
  day: string | null;
  icon: React.ReactNode;
  missing?: string;
}) {
  const sent = day && day !== "na";
  const text = sent
    ? `${label} sent ${formatDay(day)}`
    : day === "na"
      ? `${label}: not possible`
      : (missing ?? `${label} to send`);
  return (
    <span
      className={clsx(
        "inline-flex h-6 items-center gap-1 rounded-full px-2 text-[12px] font-medium",
        sent ? "bg-good-tint text-good" : "bg-chip text-muted",
      )}
      title={text}
      aria-label={text}
    >
      {sent ? <Check size={12} aria-hidden="true" /> : icon}
      {label}
    </span>
  );
}

function PersonLine({ p, today }: { p: LovedPerson; today: string }) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
      <span className="min-w-0 truncate">
        {p.name}
        <span className="text-muted"> · {p.title}</span>
      </span>
      <span className="flex shrink-0 flex-wrap items-center gap-1">
        {p.replied && <Chip tone="good">Replied</Chip>}
        <Touch
          label="Email"
          day={p.email_sent}
          icon={<Mail size={12} aria-hidden="true" />}
          missing={p.has_email ? undefined : "Email: no address yet"}
        />
        <Touch label="LinkedIn" day={p.linkedin_sent} icon={<Linkedin size={12} aria-hidden="true" />} />
        {p.due && (
          <span className="text-[12px] text-muted">
            next {p.next === "bump" ? "bump" : p.next === "dm" ? "message" : "touch"} {relativeDay(p.due, today)}
          </span>
        )}
      </span>
    </div>
  );
}

/** A job you love on Today: who's been emailed and connected with, who hasn't, and when to follow up. */
export function LovedCard({ loved, today, onOpen }: { loved: Loved; today: string; onOpen: () => void }) {
  const { company, people } = loved;
  const touches = people.length * 2;
  const done = people.reduce(
    (n, p) =>
      n + Number(!!p.email_sent && p.email_sent !== "na") + Number(!!p.linkedin_sent && p.linkedin_sent !== "na"),
    0,
  );
  const late = loved.follow_up !== null && loved.follow_up !== undefined && loved.follow_up <= today;
  return (
    <button
      type="button"
      onClick={onOpen}
      className="flex w-full flex-col gap-3 px-4 py-3.5 text-left hover:bg-chip/50 focus-visible:bg-chip/50"
    >
      <div className="flex w-full items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="flex items-center gap-1.5 text-[15px] font-semibold text-ink">
            <Heart size={14} className="fill-current text-bad" aria-hidden="true" />
            {company.name}
          </p>
          {company.open_role && <p className="text-[13px] text-muted">{company.open_role}</p>}
          {company.posted && (
            <p className="text-[12px] text-muted">
              Posted {formatDay(company.posted)} ({relativeDay(company.posted, today)})
            </p>
          )}
        </div>
        <div className="flex shrink-0 items-center gap-1.5">
          {loved.applied ? <Chip tone="good">Applied</Chip> : <Chip tone="warm">Not applied yet</Chip>}
          <ChevronRight size={16} className="text-muted" aria-hidden="true" />
        </div>
      </div>
      <p className={clsx("text-[13px] font-medium", late ? "text-bad" : "text-body")}>
        {loved.follow_up
          ? late
            ? `Follow up now: due ${relativeDay(loved.follow_up, today)}`
            : `Next follow-up ${formatDay(loved.follow_up)} (${relativeDay(loved.follow_up, today)})`
          : people.length
            ? "Nothing scheduled: check in with them"
            : "No people yet: find the hiring manager"}
        {people.length > 0 && ` · ${done} of ${touches} sent`}
      </p>
      {people.length > 0 && (
        <div className="flex w-full flex-col gap-1.5">
          {people.map((p) => (
            <PersonLine key={p.id} p={p} today={today} />
          ))}
        </div>
      )}
    </button>
  );
}
