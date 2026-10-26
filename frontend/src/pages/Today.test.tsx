import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { App } from "@/App";
import { ToastHost } from "@/components/Toast";
import { SIGNED_IN, STATS, TODAY, move } from "@/test/fixtures";
import { mockApi, renderApp } from "@/test/render";

const today = (groups: unknown[], extra: object = {}) => ({
  body: { today: TODAY, groups, overdue: 0, done_today: [], waiting: [], waiting_total: 0, ...extra },
});

describe("Today", () => {
  it("lists the day's moves by group with what each needs", async () => {
    mockApi({
      ...SIGNED_IN,
      "GET /api/stats": { body: STATS },
      "GET /api/today": today([
        {
          key: "apply",
          label: "Apply",
          moves: [
            move({
              id: "a1",
              type: "apply",
              title: "Apply: GTM Engineer",
              person: null,
              person_id: null,
              sequence: null,
              url: "https://jobs.example/1",
            }),
          ],
        },
        { key: "reach_out", label: "Reach out: email and LinkedIn request", moves: [move()] },
      ]),
    });
    renderApp(<App />);
    expect(await screen.findByRole("heading", { name: /2 moves today/ })).toBeInTheDocument();
    const reachOut = screen.getByRole("region", { name: "Reach out: email and LinkedIn request" });
    expect(within(reachOut).getByText("Email and connect with Priya Example")).toBeInTheDocument();
    expect(within(reachOut).getByRole("button", { name: "Copy email" })).toBeInTheDocument();
    expect(within(reachOut).getByText("Toronto")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open posting" })).toHaveAttribute("href", "https://jobs.example/1");
    expect(await screen.findByText("Sending")).toBeInTheDocument();
    expect(screen.getByText("4 days")).toBeInTheDocument();
  });

  it("ticks a step and asks for the list again", async () => {
    const calls = mockApi({
      ...SIGNED_IN,
      "GET /api/stats": { body: STATS },
      "GET /api/today": today([{ key: "reach_out", label: "Reach out", moves: [move()] }]),
      "POST /api/moves/m1/steps": { body: move() },
    });
    renderApp(<App />);
    await userEvent.click(await screen.findByRole("button", { name: "Emailed" }));
    const tick = calls.find((c) => c.path === "/api/moves/m1/steps");
    expect(tick?.body).toEqual({ step: "email", value: "today" });
    expect(tick?.headers.get("X-CSRF-Token")).toBe("token");
    await vi.waitFor(() => expect(calls.filter((c) => c.path === "/api/today").length).toBeGreaterThan(1));
  });

  it("offers to pull work forward when the day is clear", async () => {
    const calls = mockApi({
      ...SIGNED_IN,
      "GET /api/stats": { body: STATS },
      "GET /api/today": today([]),
      "POST /api/moves/pull": { body: { pulled: [] } },
    });
    renderApp(<App />);
    await userEvent.click(await screen.findByRole("button", { name: /Pull 3 moves forward/ }));
    expect(calls.find((c) => c.path === "/api/moves/pull")?.body).toEqual({ n: 3 });
  });

  it("says why a change failed", async () => {
    mockApi({
      ...SIGNED_IN,
      "GET /api/stats": { body: STATS },
      "GET /api/today": today([{ key: "reach_out", label: "Reach out", moves: [move()] }]),
      "POST /api/moves/m1/steps": { status: 409, body: { detail: "A step can't be done in the future." } },
    });
    renderApp(
      <>
        <App />
        <ToastHost />
      </>,
    );
    await userEvent.click(await screen.findByRole("button", { name: "Emailed" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("A step can't be done in the future.");
  });

  it("says when progress can't load, without hiding the day's moves", async () => {
    mockApi({
      ...SIGNED_IN,
      "GET /api/stats": { status: 500, body: { detail: "boom" } },
      "GET /api/today": today([{ key: "reach_out", label: "Reach out", moves: [move()] }]),
    });
    renderApp(<App />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Couldn't load your progress");
    expect(screen.getByText("Email and connect with Priya Example")).toBeInTheDocument();
  });
});
