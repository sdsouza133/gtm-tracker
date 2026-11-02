/** Lead magnets: what each build costs, and the competitors typed in. Shared by the company panel and the page. */

import type { MagnetMode } from "@/api/hooks";

export const MODES: { mode: MagnetMode; label: string; cost: string }[] = [
  {
    mode: "teaser",
    label: "Build a teaser",
    cost: "1 competitor, a few examples; up to $0.40 of Apify, plus a few cents of Claude and an Apollo credit or two",
  },
  {
    mode: "full",
    label: "Build the full list",
    cost: "up to 3 competitors, work emails where found; up to $2 of Apify, plus a few cents of Claude and an Apollo credit per email",
  },
];

/** A competitor as typed: a domain, like rival.com. */
const DOMAIN = /^(https?:\/\/)?[a-z0-9-]+(\.[a-z0-9-]+)+([/?#].*)?$/i; // a path, query or #fragment may follow

/** The competitors typed (separated by spaces or commas), and what's wrong with them, or "" when nothing is. */
export function competitors(text: string): { list: string[]; problem: string } {
  const list = text
    .split(/[\s,]+/)
    .map((r) => r.trim())
    .filter(Boolean);
  const bad = list.find((r) => !DOMAIN.test(r) || r.length > 200);
  const problem = bad
    ? `"${bad}" doesn't look like a website. Type competitors' domains, like rival.com.`
    : list.length > 5
      ? "Name up to 5 competitors."
      : "";
  return { list, problem };
}
