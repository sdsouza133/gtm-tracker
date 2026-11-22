import { screen } from "@testing-library/react";

import type { PublicLead, PublicMagnet } from "@/api/hooks";
import { App } from "@/App";
import { csvCell, toCsv } from "@/lib/leads";
import { champion, championsReport } from "@/test/fixtures";
import { mockApi, renderApp } from "@/test/render";

const NOT_SIGNED_IN = { "GET /api/auth/me": { body: { signed_in: false, csrf: null, open_access: false } } };

function lead(over: Partial<PublicLead> = {}): PublicLead {
  return {
    name: "Ana Example",
    title: "VP Sales",
    company: "Buyer Inc",
    headline: "VP Sales at Buyer Inc",
    linkedin: "https://www.linkedin.com/in/ana-example",
    country: "US",
    tier: "hot",
    points: 7,
    touches: 3,
    comments: 1,
    reactions: 2,
    posts: 2,
    competitors: ["RivalCo"],
    last: "2026-10-29",
    said: ["Great point"],
    why_fit: "Sales leader at a B2B SaaS company",
    email: null,
    ...over,
  };
}

function report(over: Partial<PublicMagnet> = {}): PublicMagnet {
  return {
    kind: "engagement",
    company: "Prospect",
    mode: "full",
    built: "2026-11-01",
    icp: {
      sells: "Pipeline software for B2B sales teams",
      industries: ["B2B SaaS"],
      company_sizes: ["50-500"],
      titles: ["VP Sales"],
      seniority: ["VP"],
      functions: ["Sales"],
    },
    competitors: [
      {
        name: "RivalCo",
        domain: "rivalco.example",
        linkedin: "https://www.linkedin.com/company/rivalco/",
        why: "Same buyers",
      },
    ],
    leads: [
      lead({ email: "ana@buyer.example" }),
      lead({
        name: "Gus Example",
        tier: "touch",
        country: "CA",
        said: [],
        touches: 1,
        comments: 0,
        reactions: 1,
        posts: 1,
      }),
    ],
    fit: 12,
    in_region: 2,
    more: 0,
    ...over,
  };
}

describe("the lead magnet report", () => {
  it("opens from its link without signing in and shows the people with how they engaged", async () => {
    const calls = mockApi({ ...NOT_SIGNED_IN, "GET /api/public/magnets/g1/tok": { body: report() } });
    renderApp(<App />, { path: "/m/g1/tok" });

    expect(await screen.findByRole("heading", { name: /engaging with RivalCo on LinkedIn/ })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Ana Example/ })).toHaveAttribute(
      "href",
      "https://www.linkedin.com/in/ana-example",
    );
    expect(screen.getByText(/3 touches: 1 comment, 2 likes across 2 posts by RivalCo/)).toBeInTheDocument();
    expect(screen.getByText("“Great point”")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /ana@buyer.example/ })).toHaveAttribute("href", "mailto:ana@buyer.example");
    expect(screen.getByRole("button", { name: /Download CSV/ })).toBeInTheDocument();
    expect(screen.getByText("Canada")).toBeInTheDocument();
    expect(screen.queryByText(/This is a preview/)).not.toBeInTheDocument();
    expect(calls.some((c) => c.path === "/login")).toBe(false);
  });

  it("calls a teaser a preview and says how many more were found", async () => {
    mockApi({ ...NOT_SIGNED_IN, "GET /api/public/magnets/g1/tok": { body: report({ mode: "teaser", more: 3 }) } });
    renderApp(<App />, { path: "/m/g1/tok" });
    expect(await screen.findByText(/3 more people found\. This is a preview/)).toBeInTheDocument();
  });

  it("says plainly when the link no longer works", async () => {
    mockApi({
      ...NOT_SIGNED_IN,
      "GET /api/public/magnets/g1/old": { status: 404, body: { detail: "This link doesn't work any more." } },
    });
    renderApp(<App />, { path: "/m/g1/old" });
    expect(await screen.findByText("This link doesn't work any more.")).toBeInTheDocument();
  });

  it("shows a champion report's top three and counts the rest, without the owner's lists", async () => {
    const shared = championsReport({
      more: 2,
      repeat: true,
      champions: [
        champion(),
        champion({ name: "Riley Example", grade: "B", new: false }),
        champion({ name: "Sam Example", grade: "C" }),
      ],
    });
    mockApi({ ...NOT_SIGNED_IN, "GET /api/public/magnets/m1/tok": { body: shared } });
    renderApp(<App />, { path: "/m/m1/tok" });

    expect(
      await screen.findByRole("heading", { name: "Your champions who just moved to new companies" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Dana Example/ })).toHaveAttribute(
      "href",
      "https://www.linkedin.com/in/dana-example",
    );
    expect(screen.getAllByText(/^Was:/)).toHaveLength(3);
    expect(screen.getAllByText("Senior Manager, Customer Experience at Glowco (2021–2026)")).toHaveLength(3);
    expect(screen.getAllByText(/VP Customer Experience at Newbrand · Retail · started 2 months ago/)).toHaveLength(3);
    expect(screen.getByText(/2 more champions found/)).toBeInTheDocument();
    expect(screen.getByText(/1 found on LinkedIn/)).toBeInTheDocument();
    expect(screen.getByText("Ghost Co · no LinkedIn page found")).toBeInTheDocument();
    // what only the owner sees
    expect(screen.queryByRole("heading", { name: "Watch list" })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Left out, and why" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Download CSV/ })).not.toBeInTheDocument();
    expect(screen.queryByText("New since the last report")).not.toBeInTheDocument();
    expect(document.title).toBe("CXHero: champions who moved");
  });

  it("writes a CSV a spreadsheet can't run as formulas", () => {
    expect(csvCell('=HYPERLINK("x")')).toBe(`"'=HYPERLINK(""x"")"`);
    expect(csvCell("-1+1")).toBe(`"'-1+1"`);
    expect(csvCell(null)).toBe('""');
    expect(csvCell("\n=1+1")).toBe(`"'\n=1+1"`); // a spreadsheet skips the line break and runs the rest
    expect(csvCell(" @SUM(A1)")).toBe(`"' @SUM(A1)"`);
    expect(csvCell("Ana Example")).toBe('"Ana Example"');
    const csv = toCsv([lead({ email: "ana@buyer.example" })]).split("\r\n");
    expect(csv[0]).toContain('"Name","Title","Company"');
    expect(csv[1]).toContain('"Ana Example","VP Sales","Buyer Inc","US","Hot"');
    expect(csv[1]).toContain('"ana@buyer.example"');
  });
});
