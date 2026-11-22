/** Champion reports: what each grade means, why people were ruled out, how a job's dates read, and the CSV. */

import type { Champion, ChampionRole, ChampionsReport, ChampionsSummary } from "@/api/hooks";
import { csvCell } from "@/lib/leads";

export type Grade = { label: string; tone: "good" | "accent" | "neutral"; meaning: string };
export const GRADE: Record<Champion["grade"], Grade> = {
  A: { label: "A · Named champion", tone: "good", meaning: "Your own website names them at a customer" },
  B: {
    label: "B · Used it",
    tone: "accent",
    meaning: "Held a role at a customer that would have used it, for six months or more, and left lately",
  },
  C: { label: "C · Was there", tone: "neutral", meaning: "Worked at one of your customers" },
};

/** Why someone who left a customer isn't in the report. The same reasons, in the same words, as the build's. */
export const REASON: Record<string, string> = {
  hidden: "LinkedIn hides who they are",
  duplicate: "Listed twice",
  no_current_role: "No current job listed",
  side_role: "Only a side role now (advisor, board, freelance...)",
  joined_vendor: "Joined the company itself",
  joined_competitor: "Joined a competitor",
  joined_customer: "Moved to another customer, which already uses it",
  junior: "Junior role",
  stale_move: "Started the new job over 3 months ago",
  outside_region: "Outside the ICP's regions",
  non_buyer_industry: "An industry that doesn't buy it (VC, staffing, universities)",
  not_icp: "The new company or role isn't in the ICP",
  no_history: "Their work history couldn't be read",
  not_verified: "Their work history shows no job at a customer",
  still_at_customer: "Still works at the customer",
  left_customer_long_ago: "Left the customer over 3 years before the new job",
  internal_move: "A new title at a company they joined earlier",
  over_cap: "Fits, but past this report's 10 work-history checks",
};

/** How long ago the new job started: "started this month", "started 2 months ago". */
export function since(months: number): string {
  if (months <= 0) return "started this month";
  return `started ${months} month${months === 1 ? "" : "s"} ago`;
}

/** A job's years: "2019–2025", "since 2024", or "" when the dates aren't known. */
export function period(role: ChampionRole): string {
  const from = role.start?.slice(0, 4);
  const to = role.end?.slice(0, 4);
  if (from && to) return from === to ? from : `${from}–${to}`;
  if (from) return `since ${from}`;
  return "";
}

/** "Head of CX at Sockfox". */
export function roleLine(role: ChampionRole): string {
  return [role.title, role.company].filter(Boolean).join(" at ");
}

const COLUMNS: [string, (c: Champion) => string | number][] = [
  ["Name", (c) => c.name],
  ["Grade", (c) => c.grade],
  ["Was", (c) => c.was.title],
  ["At customer", (c) => c.was.company],
  ["When", (c) => period(c.was)],
  ["Now", (c) => c.now.title],
  ["New company", (c) => c.now.company],
  ["Industry", (c) => c.now.industry],
  ["Months in", (c) => c.now.months],
  ["New since last report", (c) => (c.new ? "yes" : "no")],
  ["LinkedIn", (c) => c.linkedin],
  ["Why they fit", (c) => c.why],
];

/** A report's champions as CSV, with formula-safe cells. */
export function championsCsv(report: ChampionsReport): string {
  const header = COLUMNS.map(([name]) => csvCell(name)).join(",");
  const rows = report.champions.map((c) => COLUMNS.map(([, get]) => csvCell(get(c))).join(","));
  return [header, ...rows].join("\r\n");
}

/** "4 champions moved (2 A, 1 B, 1 C)", or that nobody did. */
export function championsLine(s: ChampionsSummary): string {
  if (!s.champions) return "No champions moved to a company in the ICP in the last 90 days";
  const grades = (["a", "b", "c"] as const)
    .filter((g) => s[g] > 0)
    .map((g) => `${s[g]} ${g.toUpperCase()}`)
    .join(", ");
  return `${s.champions} champion${s.champions === 1 ? "" : "s"} moved (${grades})`;
}

/** How the report got there: "4 of 5 customers found on LinkedIn · 20 left them in the last 90 days · ...". */
export function championsDetail(s: ChampionsSummary): string {
  const parts = [
    `${s.matched} of ${s.customers} customers found on LinkedIn`,
    `${s.movers} left them in the last 90 days`,
  ];
  if (s.repeat) parts.push(`${s.new} new since the last report`);
  if (s.watch) parts.push(`${s.watch} on the watch list`);
  return parts.join(" · ");
}
