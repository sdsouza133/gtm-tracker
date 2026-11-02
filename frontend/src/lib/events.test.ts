import { bodyOf, draftOf, items, planProblem } from "@/lib/events";
import { toEventCsv } from "@/lib/leads";

describe("the events helpers", () => {
  it("reads a typed list one per line, once each", () => {
    expect(items("Software\n SaaS \nsoftware\n\n  Fin   tech ")).toEqual(["Software", "SaaS", "Fin tech"]);
    expect(items("Washington, DC\nBanking, Financial Services")).toEqual([
      "Washington, DC",
      "Banking, Financial Services",
    ]);
  });

  it("sends the plan back as the server keeps it", () => {
    const draft = draftOf({
      company_name: "Acme",
      offering: "Analytics.",
      max_picked: 3,
      max_queries: 4,
      icp: {
        summary: "B2B teams.",
        industries: ["Software"],
        company_sizes: ["201-500", "51-200"],
        regions: ["United States", "Washington, DC"],
        personas: [{ label: "RevOps", title_keywords: ["revops", "revenue operations, sales"], seniorities: ["vp"] }],
      },
      events: [{ index: 0, name: "A", own: false, past: false, picked: true, queries: ['"A" going', "#A"] }],
    });
    draft.buyers.push({ label: " ", keywords: "", seniorities: [] }); // a blank buyer is left out
    draft.events[0] = { picked: true, queries: '"A" going\n\n #A ' };
    const body = bodyOf(draft, true);
    expect(body.icp.company_sizes).toEqual(["51-200", "201-500"]); // in size order
    expect(body.icp.regions).toEqual(["United States", "Washington, DC"]); // a comma stays inside its value
    expect(body.icp.personas).toEqual([
      { label: "RevOps", title_keywords: ["revops", "revenue operations, sales"], seniorities: ["vp"] },
    ]);
    expect(body.icp.exclude_title_keywords).toEqual([]);
    expect(body.events).toEqual([{ picked: true, queries: ['"A" going', "#A"] }]);
    expect(body.approve).toBe(true);
  });

  it("writes a CSV that can't run as spreadsheet formulas", () => {
    const csv = toEventCsv([
      {
        name: "=HYPERLINK(1)",
        title: "VP",
        company: "Acme",
        email: "a@acme.example",
        linkedin: "",
        event: "Summit",
        attendance: "Going",
        post: "",
        score: 80,
        reasons: ["title matches 'vp'"],
      },
    ]);
    const [header, row] = csv.split("\r\n");
    expect(header).toBe(
      '"Name","Title","Company","Email","LinkedIn","Event","Attendance","Post","ICP score","Why they fit"',
    );
    expect(row?.startsWith(`"'=HYPERLINK(1)"`)).toBe(true);
  });

  it("says what's wrong with a plan the server would refuse", () => {
    const icp = {
      summary: "B2B teams.",
      industries: ["Software"],
      company_sizes: ["51-200" as const],
      regions: ["United States"],
      personas: [{ label: "RevOps", title_keywords: ["revops"], seniorities: [] }],
      exclude_title_keywords: [],
    };
    const ok = { icp, events: [{ picked: true, queries: ['"A" going'] }], approve: false };
    expect(planProblem(ok)).toBe("");
    expect(planProblem({ ...ok, icp: { ...icp, industries: [] } })).toBe("List 1 to 12 industries, one per line.");
    expect(planProblem({ ...ok, icp: { ...icp, company_sizes: [] } })).toBe("Pick at least one company size.");
    expect(planProblem({ ...ok, icp: { ...icp, personas: [{ label: "RevOps", title_keywords: [] }] } })).toBe(
      "Give buyer 1 a name and 1 to 15 words from their job titles.",
    );
    expect(planProblem({ ...ok, events: [{ picked: true, queries: [] }] })).toBe(
      "Give each picked event 1 to 4 searches, one per line.",
    );
    expect(planProblem({ ...ok, events: [{ picked: false, queries: ["a", "b", "c", "d", "e"] }] })).toBe(
      "Give each picked event 1 to 4 searches, one per line.",
    );
    expect(planProblem({ ...ok, events: [{ picked: false, queries: [] }] })).toBe(""); // not searched, so none needed
    expect(planProblem({ ...ok, events: [{ picked: true, queries: ["x"] }] })).toBe(
      "Make each search at least 2 characters long.",
    );
    expect(planProblem({ ...ok, events: [{ picked: true, queries: ["x".repeat(301)] }] })).toBe(
      "Keep each search to 300 characters.",
    );
  });
});
