/** The events tool's helpers: money, run status, and the plan as edited (what the page holds and what it sends). */

import { type EventPlan, type EventsHome, type S, WORKING } from "@/api/hooks";

export type SizeBand = S["SizeBand"];
export type Seniority = S["Seniority"];

export const SIZES: SizeBand[] = [
  "1-10",
  "11-50",
  "51-200",
  "201-500",
  "501-1000",
  "1001-5000",
  "5001-10000",
  "10001+",
];

export function usd(amount: number): string {
  return `$${amount.toFixed(2)}`;
}

export function statusTone(status: string): "accent" | "good" | "bad" | "neutral" | "warm" {
  if (WORKING.has(status)) return "accent";
  if (status === "awaiting_approval") return "warm";
  if (status === "ready") return "good";
  if (status === "failed") return "bad";
  return "neutral";
}

/** Why the tool can't start a run right now, if it can't. */
export function blocked(home: EventsHome): string {
  if (home.open_access) return "The events tool is off while the tracker has no sign-in: its lists hold work emails.";
  if (home.missing.length) return `The events tool needs ${home.missing.join(", ")} set in Railway.`;
  if (home.paused) return "New runs are on hold.";
  return "";
}

/** 'Software, SaaS ,software' -> ['Software', 'SaaS']: comma- or line-separated, each once. */
export function items(text: string): string[] {
  const seen = new Map<string, string>();
  for (const raw of text.split(/[,\n]/)) {
    const clean = raw.split(/\s+/).filter(Boolean).join(" ");
    if (clean && !seen.has(clean.toLowerCase())) seen.set(clean.toLowerCase(), clean);
  }
  return [...seen.values()];
}

export function lines(text: string): string[] {
  return text
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
}

export type Buyer = { label: string; keywords: string; seniorities: Seniority[] };
export type Draft = {
  summary: string;
  industries: string;
  regions: string;
  exclude: string;
  sizes: SizeBand[];
  buyers: Buyer[];
  events: { picked: boolean; queries: string }[];
};

export function draftOf(plan: EventPlan): Draft {
  const icp = plan.icp;
  return {
    summary: icp.summary,
    industries: icp.industries.join(", "),
    regions: icp.regions.join(", "),
    exclude: (icp.exclude_title_keywords ?? []).join(", "),
    sizes: [...icp.company_sizes],
    buyers: icp.personas.map((p) => ({
      label: p.label,
      keywords: p.title_keywords.join(", "),
      seniorities: [...(p.seniorities ?? [])],
    })),
    events: plan.events.map((e) => ({ picked: e.picked, queries: e.queries.join("\n") })),
  };
}

export function bodyOf(draft: Draft, approve: boolean): S["EventPlanSave"] {
  return {
    icp: {
      summary: draft.summary.trim(),
      industries: items(draft.industries),
      company_sizes: SIZES.filter((size) => draft.sizes.includes(size)),
      regions: items(draft.regions),
      personas: draft.buyers
        .filter((b) => b.label.trim() || b.keywords.trim())
        .map((b) => ({ label: b.label.trim(), title_keywords: items(b.keywords), seniorities: b.seniorities })),
      exclude_title_keywords: items(draft.exclude),
    },
    events: draft.events.map((e) => ({ picked: e.picked, queries: lines(e.queries) })),
    approve,
  };
}

const SHORT = 120;
const SENTENCE = 600;
const QUERY = 300;
const QUERY_MIN = 2;

/** What's wrong with the plan as it would be sent, in words, or "" when the server will take it. The same limits as
 * the server's Icp: a refusal from its schema check would only say "something went wrong". */
export function planProblem(body: S["EventPlanSave"]): string {
  const { icp } = body;
  const tooLong = (items: string[]) => items.find((item) => item.length > SHORT);
  if (!icp.summary || icp.summary.length > SENTENCE) return "Describe who they sell to in up to 600 characters.";
  if (icp.industries.length < 1 || icp.industries.length > 12) return "List 1 to 12 industries, separated by commas.";
  if (icp.regions.length < 1 || icp.regions.length > 12)
    return "List 1 to 12 countries or regions, separated by commas.";
  if (icp.company_sizes.length < 1) return "Pick at least one company size.";
  if (icp.personas.length < 1 || icp.personas.length > 5) return "Describe 1 to 5 kinds of buyer.";
  const buyer = icp.personas.findIndex(
    (p) => !p.label || p.label.length > SHORT || p.title_keywords.length < 1 || p.title_keywords.length > 15,
  );
  if (buyer >= 0) return `Give buyer ${buyer + 1} a name and 1 to 15 words from their job titles.`;
  const exclude = icp.exclude_title_keywords ?? [];
  if (exclude.length > 20) return "List up to 20 titles that rule someone out.";
  const long = tooLong([
    ...icp.industries,
    ...icp.regions,
    ...exclude,
    ...icp.personas.flatMap((p) => p.title_keywords),
  ]);
  if (long) return `"${long.slice(0, 40)}…" is too long: keep each item to 120 characters.`;
  const searches = (e: S["EventPick"]) => e.queries ?? [];
  // a picked event needs 1 to 4 searches; an unpicked one may have none (it isn't searched)
  if (
    body.events.some((e) => (e.picked || searches(e).length > 0) && (searches(e).length < 1 || searches(e).length > 4))
  )
    return "Give each picked event 1 to 4 searches, one per line.";
  if (body.events.some((e) => searches(e).some((q) => q.length < QUERY_MIN)))
    return "Make each search at least 2 characters long.";
  if (body.events.some((e) => searches(e).some((q) => q.length > QUERY))) return "Keep each search to 300 characters.";
  return "";
}
