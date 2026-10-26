import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { RadarState } from "@/api/hooks";
import { App } from "@/App";
import { SIGNED_IN } from "@/test/fixtures";
import { mockApi, renderApp } from "@/test/render";

const state: RadarState = {
  status: {
    last_run_at: "2026-10-26T11:05:00Z",
    summary: { tracked_new: 2, linkedin_tracked: 1, inbox_new: 1, boards_checked: 40 },
  },
  config: {
    keywords: ["GTM Engineer"],
    locations: ["United States", "Canada"],
    per_search: 25,
    daily_usd: 0.3,
    hour: 7,
    min_fit: 2,
    recent_days: 7,
    ats_search: true,
    post_search: true,
    core_only: true,
    toronto_ok: true,
    min_usd: 100000,
    min_cad: 137000,
  },
  items: [
    {
      id: "li-1",
      company: "Delta Example",
      title: "GTM Engineer",
      url: "https://www.linkedin.com/jobs/view/1",
      posted: "2026-10-25",
      fit: 3,
      state: "new",
      company_id: null,
      location: "Remote",
      salary: "$150K",
      flags: ["remote", "us_only"],
      source: "LinkedIn",
      snippet: "Build our GTM systems",
      on_bench: false,
    },
  ],
  posts: [
    {
      id: "p1",
      url: "https://x.example/p1",
      posted: "",
      author: "Pat Example",
      author_url: "",
      headline: "VP Sales",
      recruiter: false,
      text: "We're hiring a GTM engineer",
    },
  ],
  apify: false,
};

describe("Radar", () => {
  it("shows the last run, the inbox and hiring posts", async () => {
    mockApi({ ...SIGNED_IN, "GET /api/radar": { body: state } });
    renderApp(<App />, { path: "/radar" });
    expect(
      await screen.findByText(/3 new at your companies · 1 new in the inbox · 40 job boards checked/),
    ).toBeInTheDocument();
    expect(screen.getByText("US work authorization")).toBeInTheDocument();
    expect(screen.getByText("Pat Example")).toBeInTheDocument();
    expect(screen.getByText(/need an Apify token/)).toBeInTheDocument();
  });

  it("adds a role, dismisses one, runs now and saves settings", async () => {
    const calls = mockApi({
      ...SIGNED_IN,
      "GET /api/radar": { body: state },
      "POST /api/radar/items/li-1/add": { body: { company_id: "c9", move_id: "m9" } },
      "POST /api/radar/items/li-1/dismiss": { body: state.items[0] },
      "POST /api/radar/run": { status: 202, body: { status: "started" } },
      "PATCH /api/radar/config": { body: state.config },
      "GET /api/companies/c9": { status: 404, body: { detail: "x" } },
    });
    renderApp(<App />, { path: "/radar" });
    await userEvent.click(await screen.findByRole("button", { name: "Dismiss GTM Engineer at Delta Example" }));
    await waitFor(() => expect(calls.some((c) => c.path === "/api/radar/items/li-1/dismiss")).toBe(true));
    await userEvent.click(screen.getByRole("button", { name: "Check now" }));
    await waitFor(() => expect(calls.some((c) => c.path === "/api/radar/run")).toBe(true));
    await userEvent.click(screen.getByRole("button", { name: "Settings" }));
    const hour = screen.getByLabelText(/Morning run at/);
    await userEvent.clear(hour);
    await userEvent.type(hour, "8");
    await userEvent.click(screen.getByRole("button", { name: "Save settings" }));
    await waitFor(() =>
      expect(calls.find((c) => c.path === "/api/radar/config")?.body).toMatchObject({
        hour: 8,
        keywords: ["GTM Engineer"],
      }),
    );
    await userEvent.click(screen.getByRole("button", { name: /Add/ }));
    await waitFor(() => expect(calls.some((c) => c.path === "/api/radar/items/li-1/add")).toBe(true));
  });
});
