import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { PublicMagnet } from "@/api/hooks";
import { App } from "@/App";
import { champion, championsMagnet, championsReport, SIGNED_IN } from "@/test/fixtures";
import { mockApi, renderApp } from "@/test/render";

const FULL = championsReport({
  repeat: true,
  champions: [
    champion(),
    champion({ name: "Riley Example", grade: "B", new: false, linkedin: "https://www.linkedin.com/in/riley-example" }),
    champion({ name: "Sam Example", grade: "C", new: false, linkedin: "https://www.linkedin.com/in/sam-example" }),
    champion({ name: "Kim Example", grade: "C", new: false, linkedin: "https://www.linkedin.com/in/kim-example" }),
  ],
  watch: [
    {
      name: "Wren Example",
      title: "Head of Support",
      company: "Shoebird",
      linkedin: "https://www.linkedin.com/in/wren-example",
      status: "still_there",
      now: "",
    },
  ],
  skipped: { junior: 2, stale_move: 1 },
  skipped_people: [
    {
      name: "Ian Example",
      linkedin: "https://www.linkedin.com/in/ian-example",
      now: "CX Intern at Bramble",
      reason: "junior",
    },
  ],
  linkedin_usd: 0.21,
});

describe("a report's full page", () => {
  it("shows the owner every champion, the watch list and who was left out, and who's new", async () => {
    mockApi({
      ...SIGNED_IN,
      "GET /api/magnets/m1": { body: championsMagnet() },
      "GET /api/magnets/m1/report": { body: FULL },
    });
    renderApp(<App />, { path: "/magnets/m1" });

    expect(
      await screen.findByRole("heading", { name: "Your champions who just moved to new companies" }),
    ).toBeInTheDocument();
    for (const name of ["Dana Example", "Riley Example", "Sam Example", "Kim Example"])
      expect(screen.getByRole("link", { name: new RegExp(name) })).toBeInTheDocument();
    expect(screen.getAllByText("New since the last report")).toHaveLength(1); // Dana only
    expect(screen.getByRole("button", { name: /Download CSV/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Copy link to send/ })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /What they'll see/ })).toHaveAttribute("href", "/m/m1/tok");

    expect(screen.getByRole("heading", { name: "Watch list" })).toBeInTheDocument();
    expect(screen.getByText(/Head of Support at Shoebird · still there/)).toBeInTheDocument();
    const left = screen.getByRole("heading", { name: "Left out, and why" }).parentElement as HTMLElement;
    expect(within(left).getByText("Junior role")).toBeInTheDocument();
    expect(within(left).getByText("Started the new job over 3 months ago")).toBeInTheDocument();
    expect(within(left).getByText(/LinkedIn data for this report: \$0\.21/)).toBeInTheDocument();
  });

  it("shows a teaser's every lead to the owner, without the preview note", async () => {
    const teaser: PublicMagnet = {
      kind: "engagement",
      company: "Prospect",
      mode: "teaser",
      built: "2026-11-01",
      icp: { sells: "", industries: [], company_sizes: [], titles: [], seniority: [], functions: [] },
      competitors: [{ name: "RivalCo", domain: "rivalco.example", linkedin: "", why: "" }],
      leads: [],
      fit: 4,
      in_region: 0,
      more: 0,
    };
    mockApi({
      ...SIGNED_IN,
      "GET /api/magnets/g1": { body: championsMagnet({ id: "g1", kind: "engagement", champions: null }) },
      "GET /api/magnets/g1/report": { body: teaser },
    });
    renderApp(<App />, { path: "/magnets/g1" });
    expect(await screen.findByRole("heading", { name: /engaging with RivalCo on LinkedIn/ })).toBeInTheDocument();
    expect(screen.queryByText(/This is a preview/)).not.toBeInTheDocument();
  });

  it("says when the link to send couldn't load, keeps the report showing, and tries again", async () => {
    const calls = mockApi({
      ...SIGNED_IN,
      "GET /api/magnets/m1": { status: 500, body: { detail: "The server had a problem." } },
      "GET /api/magnets/m1/report": { body: FULL },
    });
    renderApp(<App />, { path: "/magnets/m1" });
    expect(await screen.findByText(/Couldn't load the link to send/)).toBeInTheDocument();
    expect(
      await screen.findByRole("heading", { name: "Your champions who just moved to new companies" }),
    ).toBeInTheDocument();
    const asked = () => calls.filter((c) => c.method === "GET" && c.path === "/api/magnets/m1").length;
    const before = asked();
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    await waitFor(() => expect(asked()).toBe(before + 1));
  });

  it("says when the report isn't ready", async () => {
    mockApi({
      ...SIGNED_IN,
      "GET /api/magnets/m1": { body: championsMagnet({ status: "running", link: null, champions: null }) },
      "GET /api/magnets/m1/report": { status: 404, body: { detail: "That report isn't ready." } },
    });
    renderApp(<App />, { path: "/magnets/m1" });
    expect(await screen.findByText("That report isn't ready.")).toBeInTheDocument();
  });
});
