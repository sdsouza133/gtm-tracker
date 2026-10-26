import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { CompanyDetail } from "@/api/hooks";
import { App } from "@/App";
import { SIGNED_IN, move, person, summary } from "@/test/fixtures";
import { mockApi, renderApp } from "@/test/render";

const detail: CompanyDetail = {
  ...summary(),
  website: null,
  linkedin: null,
  notes: "",
  research: { one_liner: "AI agents for support", salary: "CA$124–137K", watch_out: "Pay tops out at your floor." },
  people: [
    person(),
    person({ id: "p2", name: "Jordan Example", role_in_hire: "peer or stakeholder", location: "Lisbon" }),
    person({ id: "p3", name: "Taylor Example", role_in_hire: "recruiter", location: "Remote" }),
  ],
  moves: [move({ id: "a1", type: "apply", title: "Apply: GTM Engineer", person_id: null, sequence: null })],
  activity: [
    {
      id: 1,
      at: "2026-10-26T14:00:00Z",
      kind: "reply",
      text: "Priya Example replied",
      company_id: "c1",
      person_id: "p1",
      move_id: null,
      xp: 10,
    },
  ],
};

describe("Company", () => {
  it("shows the role and everyone around it, filterable", async () => {
    mockApi({ ...SIGNED_IN, "GET /api/companies/c1": { body: detail } });
    renderApp(<App />, { path: "/companies/c1" });
    expect(await screen.findByRole("heading", { name: "Northwind Labs" })).toBeInTheDocument();
    expect(screen.getByText("Pay tops out at your floor.")).toBeInTheDocument();
    expect(screen.getByText("CA$124–137K")).toBeInTheDocument();
    expect(screen.getByText("3 of 3 · warmest first")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "In Toronto" }));
    expect(screen.getByText("1 of 3 · warmest first")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Recruiters" }));
    expect(screen.getByText("Taylor Example")).toBeInTheDocument();
    expect(screen.queryByText("Priya Example")).not.toBeInTheDocument();
    expect(screen.getByText(/\+10 XP/)).toBeInTheDocument();
  });

  it("adds a person with their part in the hire", async () => {
    const calls = mockApi({
      ...SIGNED_IN,
      "GET /api/companies/c1": { body: detail },
      "POST /api/people": { status: 201, body: person({ id: "p9", name: "Morgan Example" }) },
    });
    renderApp(<App />, { path: "/companies/c1" });
    await userEvent.click(await screen.findByRole("button", { name: /Add a person/ }));
    const form = screen.getByRole("form", { name: "Add a person" });
    await userEvent.type(within(form).getByLabelText("Name"), "Morgan Example");
    await userEvent.selectOptions(within(form).getByLabelText("Part in the hire"), "manager's boss");
    await userEvent.click(within(form).getByRole("button", { name: "Add person" }));
    expect(calls.find((c) => c.path === "/api/people")?.body).toMatchObject({
      company_id: "c1",
      name: "Morgan Example",
      role_in_hire: "manager's boss",
      sureness: "likely",
      email: null,
    });
  });

  it("changes the stage", async () => {
    const calls = mockApi({
      ...SIGNED_IN,
      "GET /api/companies/c1": { body: detail },
      "PATCH /api/companies/c1": { body: detail },
    });
    renderApp(<App />, { path: "/companies/c1" });
    await userEvent.selectOptions(await screen.findByLabelText("Stage"), "replied");
    expect(calls.find((c) => c.method === "PATCH")?.body).toEqual({ stage: "replied" });
  });
});
