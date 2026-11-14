import { act, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { RadarState } from "@/api/hooks";
import { App } from "@/App";
import { SIGNED_IN, STATS, TODAY } from "@/test/fixtures";
import { mockApi, renderApp } from "@/test/render";

const config: RadarState["config"] = {
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
  auto_add: true,
  auto_add_fit: 3,
  auto_add_max: 10,
  people_per_company: 4,
  people_usd: 0.3,
};
const lastRun = {
  last_run_at: "2026-10-26T11:05:00Z",
  summary: { tracked_new: 1, linkedin_tracked: 0, auto_added: 2, people_added: 5, inbox_new: 0, boards_checked: 40 },
};
const radar = (status: Record<string, unknown>): RadarState => ({ status, config, items: [], posts: [], treg: true });
const today = {
  body: {
    today: TODAY,
    groups: [],
    overdue: 0,
    more: 0,
    done_today: [],
    waiting: [],
    waiting_total: 0,
    looms: [],
  },
};

describe("Refresh", () => {
  afterEach(() => vi.useRealTimers());

  it("says when the board was last refreshed and what that added", async () => {
    mockApi({
      ...SIGNED_IN,
      "GET /api/stats": { body: STATS },
      "GET /api/today": today,
      "GET /api/radar": { body: radar(lastRun) },
    });
    renderApp(<App />);
    expect(await screen.findByText(/2 companies added, 5 people, 1 new role at yours/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Refresh" })).toBeEnabled();
  });

  it("refreshes everything, shows the progress, and reloads the page when it's done", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    let state = "idle";
    const calls = mockApi({
      ...SIGNED_IN,
      "GET /api/stats": { body: STATS },
      "GET /api/today": today,
      "GET /api/radar": {
        body: () => {
          if (state === "started") {
            state = "running";
            return radar({ ...lastRun, running: true, step: "searching LinkedIn and job boards" });
          }
          return radar(state === "running" ? { ...lastRun, last_run_at: "2026-10-27T11:05:00Z" } : lastRun);
        },
      },
      "POST /api/radar/run": {
        status: 202,
        body: () => {
          state = "started";
          return { status: "started" };
        },
      },
    });
    const user = userEvent.setup({ advanceTimers: (ms) => vi.advanceTimersByTime(ms) });
    renderApp(<App />);
    await user.click(await screen.findByRole("button", { name: "Refresh" }));
    expect(await screen.findByText("Refreshing: searching LinkedIn and job boards…")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Refreshing…" })).toBeDisabled();
    const loads = calls.filter((c) => c.path === "/api/today").length;

    await act(() => vi.advanceTimersByTimeAsync(4500)); // the next status check finds the run finished
    expect(await screen.findByRole("button", { name: "Refresh" })).toBeEnabled();
    await vi.waitFor(() => expect(calls.filter((c) => c.path === "/api/today").length).toBeGreaterThan(loads));
    expect(calls.some((c) => c.method === "POST" && c.path === "/api/radar/run")).toBe(true);
  });
});
