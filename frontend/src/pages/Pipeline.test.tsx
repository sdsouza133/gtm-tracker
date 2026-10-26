import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { App } from "@/App";
import { SIGNED_IN, summary } from "@/test/fixtures";
import { mockApi, renderApp } from "@/test/render";

const board = {
  body: {
    total: 3,
    items: [
      summary({ id: "c1", name: "Northwind Labs", stage: "contacted" }),
      summary({ id: "c2", name: "Brightline AI", stage: "not_started", people_count: 1 }),
      summary({ id: "c3", name: "Parcelly", stage: "parked", parked_reason: "Role is too old" }),
    ],
  },
};

describe("Pipeline", () => {
  it("puts each company in its stage's column and keeps parked ones aside", async () => {
    mockApi({ ...SIGNED_IN, "GET /api/companies": board });
    renderApp(<App />, { path: "/pipeline" });
    const contacted = await screen.findByRole("region", { name: "Contacted" });
    expect(within(contacted).getByRole("link", { name: "Northwind Labs" })).toBeInTheDocument();
    expect(within(screen.getByRole("region", { name: "Not started" })).getByText(/^1 person/)).toBeInTheDocument();
    expect(screen.queryByText("Parcelly")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Show parked (1)" }));
    expect(within(screen.getByRole("region", { name: "Parked" })).getByText("Role is too old")).toBeInTheDocument();
  });

  it("moves a company without dragging, from its stage menu", async () => {
    const calls = mockApi({
      ...SIGNED_IN,
      "GET /api/companies": board,
      "PATCH /api/companies/c2": { body: {} },
    });
    renderApp(<App />, { path: "/pipeline" });
    await userEvent.selectOptions(await screen.findByLabelText("Stage for Brightline AI"), "researching");
    await vi.waitFor(() => expect(calls.find((c) => c.method === "PATCH")?.body).toEqual({ stage: "researching" }));
  });

  it("searches as you type", async () => {
    const calls = mockApi({ ...SIGNED_IN, "GET /api/companies": board });
    renderApp(<App />, { path: "/pipeline" });
    await userEvent.type(await screen.findByRole("searchbox", { name: "Search companies" }), "gtm");
    await vi.waitFor(() => expect(calls.some((c) => c.path === "/api/companies" && c.method === "GET")).toBe(true));
  });
});
