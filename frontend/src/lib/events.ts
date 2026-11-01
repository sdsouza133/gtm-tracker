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
