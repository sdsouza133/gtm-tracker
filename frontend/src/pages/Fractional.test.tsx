import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { ProspectCard, ProspectDetail, S } from "@/api/hooks";
import { App } from "@/App";
import { template } from "@/components/ProspectDrawer";
import { SIGNED_IN, TODAY } from "@/test/fixtures";
import { mockApi, renderApp } from "@/test/render";

function card(over: Partial<ProspectCard> = {}): ProspectCard {
  return {
    id: "acme",
    day: TODAY,
    effective_day: TODAY,
    rank: 1,
    name: "Acme Example",
    domain: "acme.example",
    website: "https://acme.example",
    round: "$4M Seed",
    hq: "Toronto",
    employees: "12",
    dmarc: "none",
    one_liner: "Billing for vets",
    why_now: "Just raised",
    people: [{ key: "ana", name: "Ana Example", title: "CEO", linkedin: null, location: "", since: "" }],
    touched: [],
    status: "open",
    stage: "untouched",
    next_step: "Read the dossier",
    follow_up: null,
    first_touch: null,
    xp: 0,
    ...over,
  };
}

function detail(over: Partial<ProspectDetail> = {}): ProspectDetail {
  return {
    ...card(),
    linkedin: null,
    spf: "yes",
    fit: "good",
    fit_reason: "",
    offer: "An outbound system",
    pvp: "A list of 50 accounts",
    research: { one_liner: "Billing for vets", interview_hooks: ["Saw your launch"] },
    touches: {},
    steps: {},
    lost_reason: "",
    my_notes: "",
    draft: "",
    day_override: null,
    ...over,
  };
}

const stats: S["FxStats"] = {
  xp: 12,
  level: { number: 1, name: "Rookie", floor_xp: 0, next_xp: 50, next_name: "Prospector" },
  streak: 2,
  best_streak: 4,
  heat: [{ day: TODAY, hits: 1, goal: 3 }],
  clients: 0,
  monthly_revenue: 0,
  revenue_goal: 12000,
  funnel: { reached: 4, replied: 1, call: 0, proposal: 0, clients: 0 },
  badges: [{ key: "first_hit", name: "First hit", description: "Reach your first company", earned: true }],
};

const board: S["FxBoard"] = {
  today: TODAY,
  goal: 3,
  hits_today: 1,
  follow_ups_due: [
    card({
      id: "beta",
      name: "Beta Example",
      stage: "waiting",
      next_step: "Follow-up 1, due today",
      follow_up: { step: "fu1", due: TODAY },
    }),
  ],
  follow_ups_due_total: 3,
  follow_ups_later: 2,
  carried_over: [],
  carried_over_total: 0,
  todays_list: [card()],
  reached_today: [],
  coming_up: [],
  coming_up_total: 0,
  stats,
};

describe("Fractional", () => {
  it("shows today's goal, follow-ups first, and today's list", async () => {
    mockApi({ ...SIGNED_IN, "GET /api/fx/board": { body: board }, "GET /api/settings": { body: {} } });
    renderApp(<App />, { path: "/fractional" });
    expect(await screen.findByText("1/3")).toBeInTheDocument();
    expect(screen.getByText("2 to go")).toBeInTheDocument();
    const due = screen.getByRole("region", { name: "Follow-ups due" });
    expect(within(due).getByText(/2 more coming up/)).toBeInTheDocument();
    expect(within(due).getByText(/Showing the first 1 of 3; the rest are under All/)).toBeInTheDocument();
    expect(within(due).getByText("Follow-up 1, due today")).toBeInTheDocument();
    expect(screen.getByText("Billing for vets")).toBeInTheDocument();
    expect(screen.getByText("No DMARC")).toBeInTheDocument();
  });

  it("marks a follow-up sent and raises the goal", async () => {
    const calls = mockApi({
      ...SIGNED_IN,
      "GET /api/fx/board": { body: board },
      "GET /api/settings": { body: { fx_goals: { default: 3 } } },
      "PATCH /api/fx/prospects/beta": { body: detail({ id: "beta" }) },
      "PATCH /api/settings": { body: {} },
    });
    renderApp(<App />, { path: "/fractional" });
    await userEvent.click(await screen.findByRole("button", { name: "Mark sent" }));
    expect(calls.find((c) => c.path === "/api/fx/prospects/beta")?.body).toEqual({ step: { name: "fu1", on: true } });
    await userEvent.click(screen.getByRole("button", { name: "Raise today's goal" }));
    expect(calls.find((c) => c.path === "/api/settings" && c.method === "PATCH")?.body).toEqual({
      fx_goals: { default: 3, [TODAY]: 4 },
    });
  });

  it("opens the dossier and ticks a message", async () => {
    const calls = mockApi({
      ...SIGNED_IN,
      "GET /api/fx/board": { body: board },
      "GET /api/settings": { body: {} },
      "GET /api/fx/prospects/acme": { body: detail() },
      "PATCH /api/fx/prospects/acme": { body: detail({ touches: { ana: { connect: TODAY } } }) },
    });
    renderApp(<App />, { path: "/fractional" });
    await userEvent.click(await screen.findByRole("button", { name: "Open dossier" }));
    const dialog = await screen.findByRole("dialog", { name: "Acme Example" });
    await userEvent.click(within(dialog).getByRole("button", { name: /Request/ }));
    expect(calls.find((c) => c.method === "PATCH")?.body).toEqual({
      touch: { person: "ana", kind: "connect", on: true },
    });
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("keeps Tab inside the dossier and never links a non-http URL", async () => {
    const risky = detail({
      website: "javascript:alert(1)",
      research: { one_liner: "Billing", sources: ["javascript:alert(2)", "https://news.example/a", { x: 1 }] },
    });
    mockApi({
      ...SIGNED_IN,
      "GET /api/fx/board": { body: board },
      "GET /api/settings": { body: {} },
      "GET /api/fx/prospects/acme": { body: risky },
    });
    renderApp(<App />, { path: "/fractional?open=acme" });
    const dialog = await screen.findByRole("dialog", { name: "Acme Example" });
    for (const link of within(dialog).getAllByRole("link")) {
      expect(link.getAttribute("href")).toMatch(/^https:/);
    }
    await userEvent.click(within(dialog).getByRole("tab", { name: "Research" }));
    expect(within(dialog).getByRole("link", { name: "https://news.example/a" })).toBeInTheDocument();
    expect(within(dialog).getByText("javascript:alert(2)").tagName).toBe("SPAN");
    for (let i = 0; i < 40; i += 1) await userEvent.tab();
    expect(dialog.contains(document.activeElement)).toBe(true);
    await userEvent.tab({ shift: true });
    expect(dialog.contains(document.activeElement)).toBe(true);
  });

  it("writes a draft from the research", () => {
    const text = template(detail());
    expect(text).toContain("Hi Ana, I build outbound systems");
    expect(text).toContain("I put together a list of 50 accounts, free.");
    expect(text).toContain("Saw your launch");
    expect(template(detail({ pvp: "", offer: "" }))).not.toContain("I put together");
  });
});
