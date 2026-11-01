import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router-dom";

import type { EventRunSummary, EventsHome } from "@/api/hooks";
import { EventsPage } from "@/pages/Events";
import { SIGNED_IN } from "@/test/fixtures";
import { mockApi, renderApp } from "@/test/render";

export function summary(over: Partial<EventRunSummary> = {}): EventRunSummary {
  return {
    id: "r1",
    website: "https://northwind.example/",
    domain: "northwind.example",
    company_id: null,
    company_name: null,
    status: "ready",
    label: "List ready",
    detail: "The list is ready.",
    created: "2026-10-26T15:00:00Z",
    completed: "2026-10-26T16:00:00Z",
    leads: 12,
    spent_usd: 1.42,
    budget_usd: 3,
    ...over,
  };
}

function home(over: Partial<EventsHome> = {}): EventsHome {
  return {
    missing: [],
    open_access: false,
    paused: false,
    paused_by_setting: false,
    run_budget_usd: 3,
    today: { spent_usd: 1.25, reserved_usd: 0.5, cap_usd: 20, runs_started: 2 },
    queue: { due: 1, later: 0, running: 1, failed: 0 },
    runs: [summary(), summary({ id: "r2", status: "collecting", label: "Finding people", company_name: "Acme" })],
    ...over,
  };
}

function page() {
  return (
    <Routes>
      <Route path="/events" element={<EventsPage />} />
      <Route path="/events/:runId" element={<p>The run's page</p>} />
    </Routes>
  );
}

describe("the Events page", () => {
  it("shows today's spend against the cap and the latest runs", async () => {
    mockApi({ ...SIGNED_IN, "GET /api/events": { body: home() } });
    renderApp(page(), { path: "/events" });
    expect(await screen.findByText(/\$1\.75 of \$20\.00 spent today/)).toBeInTheDocument();
    const runs = screen.getByRole("list", { name: "Runs" });
    expect(runs).toHaveTextContent("northwind.exampleList ready");
    expect(screen.getByRole("link", { name: "northwind.example: List ready" })).toHaveAttribute("href", "/events/r1");
    expect(screen.getByRole("link", { name: "Acme: Finding people" })).toBeInTheDocument();
  });

  it("starts a run from a website and opens its page", async () => {
    const calls = mockApi({
      ...SIGNED_IN,
      "GET /api/events": { body: home({ runs: [] }) },
      "POST /api/events/runs": { status: 201, body: { ...summary({ id: "r9", status: "analyzing" }) } },
    });
    renderApp(page(), { path: "/events" });
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("A company's website"), "  acme.com ");
    await user.click(screen.getByRole("button", { name: "Find their event-goers" }));
    expect(await screen.findByText("The run's page")).toBeInTheDocument();
    expect(calls.find((c) => c.method === "POST")?.body).toEqual({ website: "acme.com" });
  });

  it.each([
    [{ missing: ["APIFY_TOKEN"] }, "The events tool needs APIFY_TOKEN set in Railway."],
    [{ open_access: true }, "The events tool is off while the tracker has no sign-in: its lists hold work emails."],
    [{ paused: true }, "New runs are on hold."],
  ])("says why no run can start (%o)", async (over, says) => {
    mockApi({ ...SIGNED_IN, "GET /api/events": { body: home(over) } });
    renderApp(page(), { path: "/events" });
    expect(await screen.findByText(says)).toBeInTheDocument();
    expect(screen.getByLabelText("A company's website")).toBeDisabled();
    expect(screen.getByRole("button", { name: "Find their event-goers" })).toBeDisabled();
  });

  it("holds new runs and lets them start again", async () => {
    let paused = false;
    const calls = mockApi({
      ...SIGNED_IN,
      "GET /api/events": { body: () => home({ paused }) },
      "PUT /api/events/new-runs": {
        status: 204,
        body: () => {
          paused = !paused;
          return null;
        },
      },
    });
    renderApp(page(), { path: "/events" });
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Hold new runs" }));
    expect(await screen.findByRole("button", { name: "Let new runs start" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Let new runs start" }));
    await waitFor(() =>
      expect(calls.filter((c) => c.method === "PUT").map((c) => c.body)).toEqual([{ paused: true }, { paused: false }]),
    );
  });
});
