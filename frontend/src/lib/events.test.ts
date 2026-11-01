import { bodyOf, draftOf, items } from "@/lib/events";
import { toEventCsv } from "@/lib/leads";

describe("the events helpers", () => {
  it("reads a typed list once each, comma- or line-separated", () => {
    expect(items("Software, SaaS ,software\n  Fin   tech ,")).toEqual(["Software", "SaaS", "Fin tech"]);
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
        regions: ["United States"],
        personas: [{ label: "RevOps", title_keywords: ["revops"], seniorities: ["vp"] }],
      },
      events: [{ index: 0, name: "A", own: false, past: false, picked: true, queries: ['"A" going', "#A"] }],
    });
    draft.buyers.push({ label: " ", keywords: "", seniorities: [] }); // a blank buyer is left out
    draft.events[0] = { picked: true, queries: '"A" going\n\n #A ' };
    const body = bodyOf(draft, true);
    expect(body.icp.company_sizes).toEqual(["51-200", "201-500"]); // in size order
    expect(body.icp.personas).toEqual([{ label: "RevOps", title_keywords: ["revops"], seniorities: ["vp"] }]);
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
});
