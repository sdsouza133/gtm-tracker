import type { MoveType, PersonStatus, RoleInHire, Stage, Sureness } from "@/api/hooks";

/** Dates come from the API as YYYY-MM-DD: calendar days, read as local days (never shifted by a time zone). */
export function parseDay(iso: string): Date {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(y ?? 1970, (m ?? 1) - 1, d ?? 1);
}

export function isoDay(date: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

const DAY = new Intl.DateTimeFormat("en-US", { weekday: "short", month: "short", day: "numeric" });
const LONG = new Intl.DateTimeFormat("en-US", { weekday: "long", month: "long", day: "numeric" });
const TIME = new Intl.DateTimeFormat("en-US", { hour: "numeric", minute: "2-digit" });

export const formatDay = (iso: string) => DAY.format(parseDay(iso));
export const formatLongDay = (iso: string) => LONG.format(parseDay(iso));
export const formatTime = (iso: string) => TIME.format(new Date(iso));
/** The local calendar day of a timestamp (not its UTC date, which is tomorrow for an evening in Toronto). */
export const formatDateTimeDay = (iso: string) => DAY.format(new Date(iso));

export function daysBetween(fromIso: string, toIso: string): number {
  return Math.round((parseDay(toIso).getTime() - parseDay(fromIso).getTime()) / 86_400_000);
}

/** "today", "tomorrow", "in 3 days", "2 days ago". */
export function relativeDay(iso: string, todayIso: string): string {
  const n = daysBetween(todayIso, iso);
  if (n === 0) return "today";
  if (n === 1) return "tomorrow";
  if (n === -1) return "yesterday";
  return n > 0 ? `in ${n} days` : `${-n} days ago`;
}

/** The next working day after `iso` (a "later" that never lands on a weekend). */
export function nextWorkday(iso: string): string {
  const d = parseDay(iso);
  do d.setDate(d.getDate() + 1);
  while (d.getDay() === 0 || d.getDay() === 6);
  return isoDay(d);
}

export function initials(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0]?.toUpperCase())
    .join("");
}

export const STAGES: { key: Stage; label: string }[] = [
  { key: "not_started", label: "Not started" },
  { key: "researching", label: "Researching" },
  { key: "contacted", label: "Contacted" },
  { key: "replied", label: "Replied" },
  { key: "call_booked", label: "Call booked" },
  { key: "interviewing", label: "Interviewing" },
  { key: "take_home", label: "Take-home" },
  { key: "offer", label: "Offer" },
  { key: "parked", label: "Parked" },
  { key: "rejected", label: "Rejected" },
  { key: "bench", label: "Bench" },
];
export const stageLabel = (s: Stage) => STAGES.find((x) => x.key === s)?.label ?? s;

export const ROLE_LABEL: Record<RoleInHire, string> = {
  "hiring manager": "Hiring manager",
  approver: "Approver",
  "manager's boss": "Manager's boss",
  boss: "Boss",
  both: "Hiring manager + approver",
  founder: "Founder",
  recruiter: "Recruiter",
  poster: "Posted the role",
  "peer or stakeholder": "Team",
};

export const SURE_LABEL: Record<Sureness, string> = { confirmed: "Confirmed", likely: "Likely", guess: "Guess" };

export const STATUS_LABEL: Record<PersonStatus, string> = {
  none: "Not contacted",
  requested: "Request sent",
  connected: "Connected",
  replied: "Replied",
  no_response: "No response",
  declined: "Declined",
};

export const MOVE_LABEL: Record<MoveType, string> = {
  reach: "Reach out",
  apply: "Apply",
  email: "Email",
  approver_email: "Email the approver",
  connect: "Connect",
  comment: "Comment",
  bump: "Bump",
  linkedin_dm: "LinkedIn message",
  call: "Call",
  interview: "Interview",
  take_home: "Take-home",
  follow_up: "Follow up",
  research: "Research",
  prep: "Prep",
  build: "Build",
  post: "Post",
  review: "Review",
  custom: "Other",
};

export const LEADERS: ReadonlySet<RoleInHire> = new Set([
  "hiring manager",
  "approver",
  "manager's boss",
  "boss",
  "both",
  "founder",
]);
