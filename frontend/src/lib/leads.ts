/** Lead lists: a lead magnet's people (what each tier means, and the CSV its report downloads), and an events run's. */

import type { EventLead, PublicLead } from "@/api/hooks";

export type Tier = { label: string; tone: "bad" | "warm" | "neutral"; meaning: string };
export const SINGLE: Tier = {
  label: "Single touch",
  tone: "neutral",
  meaning: "One like. A touchpoint, not a sign they're buying",
};
export const TIER: Record<string, Tier> = {
  hot: {
    label: "Hot",
    tone: "bad",
    meaning: "Commented at two competitors, or engaged three or more times across two or more posts",
  },
  warm: { label: "Warm", tone: "warm", meaning: "Engaged twice, or left a comment" },
  touch: SINGLE,
};

const CSV_COLUMNS: [string, (l: PublicLead) => string | number | null][] = [
  ["Name", (l) => l.name],
  ["Title", (l) => l.title],
  ["Company", (l) => l.company],
  ["Country", (l) => l.country],
  ["Tier", (l) => TIER[l.tier]?.label ?? l.tier],
  ["Touches", (l) => l.touches],
  ["Comments", (l) => l.comments],
  ["Likes", (l) => l.reactions],
  ["Posts", (l) => l.posts],
  ["Competitors", (l) => l.competitors.join("; ")],
  ["Last touch", (l) => l.last],
  ["Email", (l) => l.email],
  ["LinkedIn", (l) => l.linkedin],
  ["Why they fit", (l) => l.why_fit],
];

/** One CSV cell: quoted, and a leading = + - @ (or whitespace, which a spreadsheet skips before one) neutralised so
 * it never runs as a formula. */
export function csvCell(value: string | number | null): string {
  let text = value === null ? "" : String(value);
  if (/^[\s=+\-@]/.test(text)) text = `'${text}`;
  return `"${text.replace(/"/g, '""')}"`;
}

export function toCsv(leads: PublicLead[]): string {
  const header = CSV_COLUMNS.map(([name]) => csvCell(name)).join(",");
  const rows = leads.map((l) => CSV_COLUMNS.map(([, get]) => csvCell(get(l))).join(","));
  return [header, ...rows].join("\r\n");
}

const EVENT_COLUMNS: [string, (l: EventLead) => string | number][] = [
  ["Name", (l) => l.name],
  ["Title", (l) => l.title],
  ["Company", (l) => l.company],
  ["Email", (l) => l.email],
  ["LinkedIn", (l) => l.linkedin],
  ["Event", (l) => l.event],
  ["Attendance", (l) => l.attendance],
  ["Post", (l) => l.post],
  ["ICP score", (l) => l.score],
  ["Why they fit", (l) => l.reasons.join("; ")],
];

/** An events run's list as CSV, with the same formula-safe cells. */
export function toEventCsv(leads: EventLead[]): string {
  const header = EVENT_COLUMNS.map(([name]) => csvCell(name)).join(",");
  const rows = leads.map((l) => EVENT_COLUMNS.map(([, get]) => csvCell(get(l))).join(","));
  return [header, ...rows].join("\r\n");
}
