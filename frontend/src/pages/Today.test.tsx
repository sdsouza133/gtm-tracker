import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { App } from "@/App";
import { ToastHost } from "@/components/Toast";
import type { MoveCard, S } from "@/api/hooks";
import { SIGNED_IN, STATS, TODAY, company, move, person, summary } from "@/test/fixtures";
import { mockApi, renderApp } from "@/test/render";

const today = (groups: unknown[], extra: object = {}) => ({
  body: {
    today: TODAY,
    groups,
    overdue: 0,
    more: 0,
    done_today: [],
    waiting: [],
    waiting_total: 0,
    looms: [],
    ...extra,
  },
});

function moveOut(card: MoveCard): S["MoveOut"] {
  const out: Partial<MoveCard> = { ...card };
  delete out.company;
  delete out.person;
  return out as S["MoveOut"];
}
const reachOut = moveOut(move());
const detail: S["CompanyDetail"] = {
  ...summary(),
  website: "https://northwind.example",
  linkedin: null,
  notes: "",
  research: { pmf_reason: "Makes made-up widgets for testing." },
  people: [person()],
  moves: [reachOut],
  activity: [],
};
const applyMove = move({
  id: "a1",
  type: "apply",
  title: "Apply: GTM Engineer",
  person: null,
  person_id: null,
  sequence: null,
  url: "https://jobs.example/1",
});

function firstSent(panel: HTMLElement): HTMLElement {
  const [email] = within(panel).getAllByRole("button", { name: "Sent" });
  if (!email) throw new Error("no Sent button");
  return email;
}

describe("Today", () => {
  it("shows one card per company, with an email and a LinkedIn tick for each person", async () => {
    mockApi({
      ...SIGNED_IN,
      "GET /api/stats": { body: STATS },
      "GET /api/today": today([
        { key: "apply", label: "Apply", moves: [applyMove] },
        { key: "reach_out", label: "Reach out", moves: [move()] },
      ]),
    });
    renderApp(<App />);
    expect(await screen.findByRole("heading", { name: /1 company today/ })).toBeInTheDocument();
    const card = screen.getByRole("button", { name: /Northwind Labs/ });
    expect(within(card).getByText("Priya Example")).toBeInTheDocument();
    expect(within(card).getByText("0 of 2 sent")).toBeInTheDocument();
    expect(within(card).getByLabelText("Email to send")).toBeInTheDocument();
    expect(within(card).getByText("Apply")).toBeInTheDocument();
    expect(await screen.findByText("Sending")).toBeInTheDocument();
  });

  it("opens the company and ticks the email as sent", async () => {
    const calls = mockApi({
      ...SIGNED_IN,
      "GET /api/stats": { body: STATS },
      "GET /api/today": today([{ key: "reach_out", label: "Reach out", moves: [move()] }]),
      "GET /api/companies/c1": { body: detail },
      "POST /api/moves/m1/steps": { body: move() },
    });
    renderApp(<App />);
    await userEvent.click(await screen.findByRole("button", { name: /Northwind Labs/ }));
    const panel = await screen.findByRole("dialog", { name: "Northwind Labs" });
    expect(within(panel).getByText("Makes made-up widgets for testing.")).toBeInTheDocument();
    expect(within(panel).getByText("Score 4.2")).toBeInTheDocument();
    expect(within(panel).getByRole("link", { name: "priya@northwind.example" })).toBeInTheDocument();
    await userEvent.click(firstSent(panel));
    await vi.waitFor(() => expect(calls.some((c) => c.path === "/api/moves/m1/steps")).toBe(true));
    const tick = calls.find((c) => c.path === "/api/moves/m1/steps");
    expect(tick?.body).toEqual({ step: "email", value: "today" });
    expect(tick?.headers.get("X-CSRF-Token")).toBe("token");
  });

  it("keeps the posting and what you did with the application, and lets you undo it", async () => {
    const applied = { ...moveOut(applyMove), status: "done" as const, done_at: "2026-10-26T15:00:00Z" };
    const calls = mockApi({
      ...SIGNED_IN,
      "GET /api/stats": { body: STATS },
      "GET /api/today": today([{ key: "reach_out", label: "Reach out", moves: [move()] }]),
      "GET /api/companies/c1": { body: { ...detail, open_role: "GTM Engineer", moves: [reachOut, applied] } },
      "PATCH /api/moves/a1": { body: { ...applied, status: "open" } },
    });
    renderApp(<App />);
    await userEvent.click(await screen.findByRole("button", { name: /Northwind Labs/ }));
    const panel = await screen.findByRole("dialog", { name: "Northwind Labs" });
    expect(within(panel).getByRole("link", { name: /Open posting/ })).toHaveAttribute("href", "https://jobs.example/1");
    expect(within(panel).getByText(/Applied/)).toBeInTheDocument();
    await userEvent.click(within(panel).getByRole("button", { name: "Undo" }));
    await vi.waitFor(() => expect(calls.some((c) => c.path === "/api/moves/a1")).toBe(true));
    expect(calls.find((c) => c.path === "/api/moves/a1")?.body).toEqual({ status: "open" });
  });

  it("shows the company's other to-dos with Done, and parks a company that's not for you", async () => {
    const prep = { ...moveOut(applyMove), id: "x1", type: "prep" as const, title: "Prep for the interview", url: null };
    const calls = mockApi({
      ...SIGNED_IN,
      "GET /api/stats": { body: STATS },
      "GET /api/today": today([{ key: "reach_out", label: "Reach out", moves: [move()] }]),
      "GET /api/companies/c1": { body: { ...detail, moves: [reachOut, prep] } },
      "PATCH /api/moves/x1": { body: { ...prep, status: "done" } },
      "PATCH /api/companies/c1": { body: { ...detail, stage: "parked" } },
    });
    renderApp(<App />);
    await userEvent.click(await screen.findByRole("button", { name: /Northwind Labs/ }));
    const panel = await screen.findByRole("dialog", { name: "Northwind Labs" });
    expect(within(panel).getByText("Prep for the interview")).toBeInTheDocument();
    await userEvent.click(within(panel).getByRole("button", { name: "Done" }));
    await vi.waitFor(() => expect(calls.find((c) => c.path === "/api/moves/x1")?.body).toEqual({ status: "done" }));
    await userEvent.click(within(panel).getByRole("button", { name: /Not for me/ }));
    await vi.waitFor(() =>
      expect(calls.find((c) => c.method === "PATCH" && c.path === "/api/companies/c1")?.body).toEqual({
        stage: "parked",
      }),
    );
  });

  it("gets Today's companies ready, and looks up a missing email when a company opens", async () => {
    const noEmail = { ...detail, people: [person({ email: null })] };
    const tried = { ...detail, people: [person({ email: null, details: { apollo_tried: "2026-10-26" } })] };
    const looked = () => calls.some((c) => c.path === "/api/companies/c1/enrich");
    const calls = mockApi({
      ...SIGNED_IN,
      "GET /api/stats": { body: STATS },
      "GET /api/today": today([{ key: "reach_out", label: "Reach out", moves: [move()] }]),
      "GET /api/companies/c1": { body: () => (looked() ? tried : noEmail) },
      "POST /api/enrich/today": { body: { tried: 0, found: 0, companies: 1 } },
      "POST /api/companies/c1/enrich": { body: { tried: 1, found: 0, companies: 1 } },
    });
    renderApp(<App />);
    await vi.waitFor(() => expect(calls.some((c) => c.path === "/api/enrich/today")).toBe(true));
    await userEvent.click(await screen.findByRole("button", { name: /Northwind Labs/ }));
    await vi.waitFor(() => expect(calls.some((c) => c.path === "/api/companies/c1/enrich")).toBe(true));
    expect(await screen.findByText("No email found")).toBeInTheDocument();
    expect(calls.filter((c) => c.path === "/api/companies/c1/enrich")).toHaveLength(1);
  });

  it("says when an email lookup fails, and lets you try again", async () => {
    const calls = mockApi({
      ...SIGNED_IN,
      "GET /api/stats": { body: STATS },
      "GET /api/today": today([{ key: "reach_out", label: "Reach out", moves: [move()] }]),
      "GET /api/companies/c1": { body: { ...detail, people: [person({ email: null })] } },
      "POST /api/enrich/today": { status: 409, body: { detail: "Apollo isn't set up (APOLLO_API_KEY)." } },
      "POST /api/companies/c1/enrich": { status: 502, body: { detail: "Apollo is down" } },
    });
    renderApp(
      <>
        <App />
        <ToastHost />
      </>,
    );
    await vi.waitFor(() => expect(calls.some((c) => c.path === "/api/enrich/today")).toBe(true));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument(); // Today's 409, "not set up yet", stays quiet
    await userEvent.click(await screen.findByRole("button", { name: /Northwind Labs/ }));
    expect(await screen.findByText("Couldn't look up the email")).toBeInTheDocument();
    expect(await screen.findByRole("alert")).toHaveTextContent("Apollo is down"); // anything else says so
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    await vi.waitFor(() => expect(calls.filter((c) => c.path === "/api/companies/c1/enrich")).toHaveLength(2));
  });

  it("lists Loom requests until the Loom is sent", async () => {
    const calls = mockApi({
      ...SIGNED_IN,
      "GET /api/stats": { body: STATS },
      "GET /api/today": today([], { looms: [{ person: person(), company: company() }] }),
      "PATCH /api/people/p1": { body: person() },
    });
    renderApp(<App />);
    const looms = await screen.findByRole("region", { name: "Loom requests" });
    expect(within(looms).getByText("Priya Example")).toBeInTheDocument();
    await userEvent.click(within(looms).getByRole("button", { name: "Loom sent" }));
    await vi.waitFor(() => expect(calls.find((c) => c.path === "/api/people/p1")?.body).toEqual({ loom: "sent" }));
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
      "GET /api/companies/c1": { body: detail },
      "POST /api/moves/m1/steps": { status: 409, body: { detail: "A step can't be done in the future." } },
    });
    renderApp(
      <>
        <App />
        <ToastHost />
      </>,
    );
    await userEvent.click(await screen.findByRole("button", { name: /Northwind Labs/ }));
    const panel = await screen.findByRole("dialog", { name: "Northwind Labs" });
    await userEvent.click(firstSent(panel));
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
    expect(screen.getByRole("button", { name: /Northwind Labs/ })).toBeInTheDocument();
  });

  it("says the day is done when the daily limit is reached", async () => {
    mockApi({ ...SIGNED_IN, "GET /api/stats": { body: STATS }, "GET /api/today": today([], { more: 8 }) });
    renderApp(<App />);
    expect(await screen.findByText("Done for today. Nice work.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Pull 3 moves/ })).not.toBeInTheDocument();
  });
});
