import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router-dom";

import type { EventLead, EventRun, PlanEvent } from "@/api/hooks";
import { ToastHost } from "@/components/Toast";
import { EventRunPage } from "@/pages/EventRun";
import { SIGNED_IN } from "@/test/fixtures";
import { mockApi, renderApp } from "@/test/render";

function event(index: number, over: Partial<PlanEvent> = {}): PlanEvent {
  return {
    index,
    name: `Summit ${index + 1}`,
    start_date: "2026-11-1" + String(index),
    end_date: null,
    location: "Austin, United States",
    url: `https://summit${index + 1}.example`,
    why: "Their buyers speak there.",
    own: false,
    past: false,
    picked: index < 3,
    queries: [`"Summit ${index + 1}" attending`],
    ...over,
  };
}

function run(over: Partial<EventRun> = {}): EventRun {
  return {
    id: "r1",
    website: "https://northwind.example/",
    domain: "northwind.example",
    company_id: "c1",
    company_name: "Northwind",
    status: "awaiting_approval",
    label: "Plan ready to review",
    detail: "The plan is ready to review.",
    created: "2026-10-26T15:00:00Z",
    completed: null,
    leads: 0,
    spent_usd: 0.31,
    budget_usd: 3,
    error: "",
    working: false,
    progress: null,
    found: null,
    expires: null,
    plan: {
      company_name: "Northwind Analytics",
      offering: "Revenue analytics for B2B teams.",
      max_picked: 3,
      max_queries: 4,
      icp: {
        summary: "Revenue teams at B2B software companies.",
        industries: ["Software"],
        company_sizes: ["51-200", "201-500"],
        regions: ["United States"],
        personas: [{ label: "RevOps leaders", title_keywords: ["revops"], seniorities: ["vp"] }],
        exclude_title_keywords: ["recruiter"],
      },
      events: [event(0), event(1), event(2), event(3, { own: true, picked: false, why: null })],
    },
    ...over,
  };
}

function lead(over: Partial<EventLead> = {}): EventLead {
  return {
    name: "Ana Example",
    title: "VP Revenue Operations",
    company: "Buyer Inc",
    email: "ana@buyer.example",
    linkedin: "https://www.linkedin.com/in/ana-example",
    event: "Summit 1",
    attendance: "Speaking",
    post: "https://www.linkedin.com/posts/ana-1",
    score: 88,
    reasons: ["title matches 'revenue operations'"],
    ...over,
  };
}

const RUN = "GET /api/events/runs/r1";

function page() {
  return (
    <Routes>
      <Route path="/events/:runId" element={<EventRunPage />} />
    </Routes>
  );
}

describe("an events run's page", () => {
  it("shows the plan with the first three events picked and approves it as edited", async () => {
    const calls = mockApi({
      ...SIGNED_IN,
      [RUN]: { body: run() },
      "PUT /api/events/runs/r1/plan": {
        body: () => run({ status: "collecting", label: "Finding people", working: true, plan: null }),
      },
    });
    renderApp(page(), { path: "/events/r1" });
    const user = userEvent.setup();

    expect(await screen.findByText("Northwind Analytics")).toBeInTheDocument();
    expect(screen.getByText(/3 of 3 picked/)).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: /Search Summit 4/ })).toBeDisabled(); // three picked already
    await user.click(screen.getByRole("checkbox", { name: /Search Summit 2/ }));
    await user.click(screen.getByRole("checkbox", { name: /Search Summit 4/ }));
    const summary = screen.getByLabelText("In a sentence or two");
    await user.clear(summary);
    await user.type(summary, "RevOps teams at mid-size SaaS.");
    await user.click(screen.getByRole("button", { name: "Find the people" }));

    await waitFor(() => expect(calls.some((c) => c.method === "PUT")).toBe(true));
    const body = calls.find((c) => c.method === "PUT")?.body as {
      icp: { summary: string; company_sizes: string[] };
      events: { picked: boolean; queries: string[] }[];
      approve: boolean;
    };
    expect(body.approve).toBe(true);
    expect(body.icp.summary).toBe("RevOps teams at mid-size SaaS.");
    expect(body.icp.company_sizes).toEqual(["51-200", "201-500"]);
    expect(body.events.map((e) => e.picked)).toEqual([true, false, true, true]);
    expect(body.events[0]?.queries).toEqual(['"Summit 1" attending']);
  });

  it("says what the server refused, and keeps the plan as typed", async () => {
    mockApi({
      ...SIGNED_IN,
      [RUN]: { body: run() },
      "PUT /api/events/runs/r1/plan": { status: 422, body: { detail: "Pick up to 3 events." } },
    });
    renderApp(
      <>
        <ToastHost />
        {page()}
      </>,
      { path: "/events/r1" },
    );
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Save the plan" }));
    expect(await screen.findByText("Pick up to 3 events.")).toBeInTheDocument();
    expect(screen.getByLabelText("In a sentence or two")).toHaveValue("Revenue teams at B2B software companies.");
  });

  it("names what to fix in the plan before sending it", async () => {
    const calls = mockApi({ ...SIGNED_IN, [RUN]: { body: run() } });
    renderApp(
      <>
        <ToastHost />
        {page()}
      </>,
      { path: "/events/r1" },
    );
    const user = userEvent.setup();
    await user.clear(await screen.findByLabelText(/^Industries/));
    await user.click(screen.getByRole("button", { name: "Save the plan" }));
    expect(await screen.findByText("List 1 to 12 industries, separated by commas.")).toBeInTheDocument();
    expect(calls.some((c) => c.method === "PUT")).toBe(false);
  });

  it("adds an event you know after saving what's typed", async () => {
    const calls = mockApi({
      ...SIGNED_IN,
      [RUN]: { body: run() },
      "PUT /api/events/runs/r1/plan": { body: run() },
      "POST /api/events/runs/r1/events": {
        body: () => {
          const before = run();
          const plan = before.plan;
          if (!plan) throw new Error("no plan");
          return run({
            plan: {
              ...plan,
              events: [...plan.events, event(4, { name: "Demand Gen Live", own: true, picked: false })],
            },
          });
        },
      },
    });
    renderApp(page(), { path: "/events/r1" });
    const user = userEvent.setup();
    const form = (await screen.findByRole("heading", { name: "Add an event you know" })).closest("form");
    if (!form) throw new Error("no form");
    await user.type(within(form).getByLabelText("Name"), "Demand Gen Live");
    await user.click(within(form).getByRole("button", { name: "Add this event" }));
    expect(await screen.findByRole("checkbox", { name: /Search Demand Gen Live/ })).toBeInTheDocument();
    expect(within(form).getByLabelText("Name")).toHaveValue(""); // cleared, so a second click can't add it again
    expect(calls.filter((c) => c.method !== "GET").map((c) => c.method)).toEqual(["PUT", "POST"]);
    expect(calls.find((c) => c.method === "POST")?.body).toEqual({ name: "Demand Gen Live", day: null, url: null });
  });

  it("shows a working run's steps and what it has found so far", async () => {
    mockApi({
      ...SIGNED_IN,
      [RUN]: {
        body: run({
          status: "qualifying",
          label: "Finding people",
          working: true,
          plan: null,
          progress: {
            steps: ["Searching", "Checking who's really going", "Finding verified emails"],
            step: 1,
            note: "",
          },
          found: { posts: 120, people: 34, emails: 0, percent: 45 },
        }),
      },
    });
    renderApp(page(), { path: "/events/r1" });
    expect(await screen.findByText("Checking who's really going (under way)")).toBeInTheDocument();
    expect(screen.getByText("Searching (done)")).toBeInTheDocument();
    expect(screen.getByRole("progressbar", { name: "How far along the search is" })).toHaveAttribute(
      "aria-valuenow",
      "45",
    );
    expect(screen.getByText(/120 posts found · 34 people at the events · 0 verified emails/)).toBeInTheDocument();
  });

  it("cancels a run that hasn't finished, once confirmed", async () => {
    const calls = mockApi({
      ...SIGNED_IN,
      [RUN]: { body: run({ status: "collecting", label: "Finding people", working: true, plan: null }) },
      "POST /api/events/runs/r1/cancel": { body: run({ status: "canceled", label: "Canceled", plan: null }) },
    });
    const confirm = vi.spyOn(window, "confirm").mockReturnValueOnce(false).mockReturnValueOnce(true);
    renderApp(page(), { path: "/events/r1" });
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Cancel run" }));
    expect(calls.some((c) => c.method === "POST")).toBe(false);
    await user.click(screen.getByRole("button", { name: "Cancel run" }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST")).toBe(true));
    expect(confirm).toHaveBeenCalledTimes(2);
    confirm.mockRestore();
  });

  it("lists a finished run's people and downloads them as CSV", async () => {
    mockApi({
      ...SIGNED_IN,
      [RUN]: {
        body: run({ status: "ready", label: "List ready", plan: null, leads: 2, expires: "2026-11-25T16:00:00Z" }),
      },
      "GET /api/events/runs/r1/leads": {
        body: [
          lead(),
          lead({ name: "Ben Example", attendance: "Going", email: "", post: "javascript:alert(1)", score: 70 }),
        ],
      },
    });
    const created = vi.fn(() => "blob:leads");
    URL.createObjectURL = created;
    URL.revokeObjectURL = vi.fn();
    renderApp(page(), { path: "/events/r1" });
    const user = userEvent.setup();
    const list = await screen.findByRole("list", { name: "Leads" });
    expect(within(list).getAllByRole("listitem")).toHaveLength(2);
    expect(within(list).getByRole("link", { name: "Ana Example" })).toHaveAttribute(
      "href",
      "https://www.linkedin.com/in/ana-example",
    );
    expect(within(list).queryAllByRole("link", { name: /Their post/ })).toHaveLength(1); // no script link
    await user.click(screen.getByRole("button", { name: "Download CSV" }));
    expect(created).toHaveBeenCalledTimes(1);
  });

  it("says why a run stopped", async () => {
    mockApi({
      ...SIGNED_IN,
      [RUN]: {
        body: run({
          status: "failed",
          label: "Stopped",
          plan: null,
          detail: "Couldn't read northwind.example: the site took too long.",
          error: "ReadTimeout",
        }),
      },
    });
    renderApp(page(), { path: "/events/r1" });
    expect(await screen.findByText("Couldn't read northwind.example: the site took too long.")).toBeInTheDocument();
    expect(screen.getByText("Details: ReadTimeout")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Cancel run" })).not.toBeInTheDocument();
  });
});
