import { championsCsv, championsDetail, championsLine, period, REASON, since } from "@/lib/champions";
import { domainOf } from "@/lib/magnets";
import { champion, championsReport, championsSummary } from "@/test/fixtures";

describe("champion report wording", () => {
  it("says how long ago the new job started", () => {
    expect(since(0)).toBe("started this month");
    expect(since(1)).toBe("started 1 month ago");
    expect(since(3)).toBe("started 3 months ago");
  });

  it("reads a job's years", () => {
    const role = champion().was;
    expect(period(role)).toBe("2021–2026");
    expect(period({ ...role, end: "2021-11-01" })).toBe("2021");
    expect(period({ ...role, end: null })).toBe("since 2021");
    expect(period({ ...role, start: null, end: null })).toBe("");
  });

  it("sums a report up", () => {
    expect(championsLine(championsSummary())).toBe("4 champions moved (2 A, 1 B, 1 C)");
    expect(championsLine(championsSummary({ champions: 1, a: 0, b: 1, c: 0 }))).toBe("1 champion moved (1 B)");
    expect(championsLine(championsSummary({ champions: 0, a: 0, b: 0, c: 0 }))).toMatch(/^No champions moved/);
    expect(championsDetail(championsSummary())).toBe(
      "4 of 5 customers found on LinkedIn · 20 left them in the last 90 days · 2 on the watch list",
    );
    expect(championsDetail(championsSummary({ repeat: true, new: 1, watch: 0 }))).toBe(
      "4 of 5 customers found on LinkedIn · 20 left them in the last 90 days · 1 new since the last report",
    );
  });

  it("names every reason the build can give", () => {
    expect(Object.keys(REASON).sort()).toEqual(
      [
        "hidden",
        "duplicate",
        "no_current_role",
        "side_role",
        "joined_vendor",
        "joined_competitor",
        "joined_customer",
        "junior",
        "stale_move",
        "outside_region",
        "non_buyer_industry",
        "not_icp",
        "no_history",
        "not_verified",
        "still_at_customer",
        "left_customer_long_ago",
        "internal_move",
        "over_cap",
      ].sort(),
    );
  });

  it("writes the champions as a CSV a spreadsheet can't run as formulas", () => {
    const csv = championsCsv(championsReport({ champions: [champion({ name: "=HYPERLINK(1)" })] })).split("\r\n");
    expect(csv[0]).toBe(
      '"Name","Grade","Was","At customer","When","Now","New company","Industry","Months in","New since last report","LinkedIn","Why they fit"',
    );
    expect(csv[1]).toContain(`"'=HYPERLINK(1)","A","Senior Manager, Customer Experience","Glowco","2021–2026"`);
  });

  it("says who's new since the last report only on a rebuild", () => {
    const first = championsCsv(championsReport()).split("\r\n");
    expect(first[1]).toContain('"2","","https://www.linkedin.com/in/dana-example"'); // blank: nothing to compare with
    const again = championsReport({ repeat: true, champions: [champion(), champion({ new: false })] });
    const rows = championsCsv(again).split("\r\n");
    expect(rows[1]).toContain('"2","yes","https://www.linkedin.com/in/dana-example"');
    expect(rows[2]).toContain('"2","no","https://www.linkedin.com/in/dana-example"');
  });

  it("matches a website to a company by its bare domain", () => {
    expect(domainOf("https://www.CXHero.example/customers?x=1")).toBe("cxhero.example");
    expect(domainOf("http://cxhero.example:8443/x")).toBe("cxhero.example:8443"); // a port stays, as on the server
    expect(domainOf("  ")).toBe("");
  });
});
