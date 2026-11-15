import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { Magnet } from "@/api/hooks";
import { MagnetsPage } from "@/pages/Magnets";
import { SIGNED_IN } from "@/test/fixtures";
import { mockApi, renderApp } from "@/test/render";

function magnet(over: Partial<Magnet> = {}): Magnet {
  return {
    id: "g1",
    company_id: "c1",
    kind: "engagement",
    status: "ready",
    title: "Northwind Labs: teaser",
    mode: "teaser",
    website: "https://northwind.example",
    step: "",
    error: "",
    created: "2026-10-26T15:00:00Z",
    link: "/m/g1/tok",
    views: 2,
    summary: { leads: 3, hot: 1, warm: 2, touch: 0, emails: 0, fit: 9, people: 40, linkedin_usd: 0.21 },
    ...over,
  };
}

const LIST = "GET /api/magnets";

describe("the lead magnets page", () => {
  it("lists every lead magnet by its title, from the tracker's companies and from any website", async () => {
    mockApi({
      ...SIGNED_IN,
      [LIST]: {
        body: [magnet({ id: "g2", company_id: null, title: "acme.example: full list", mode: "full" }), magnet()],
      },
    });
    renderApp(<MagnetsPage />);
    const list = await screen.findByRole("list", { name: "Lead magnets" });
    const rows = within(list).getAllByRole("listitem");
    expect(rows).toHaveLength(2);
    expect(within(rows[0] as HTMLElement).getByText("acme.example: full list")).toBeInTheDocument();
    expect(within(rows[1] as HTMLElement).getByText("Northwind Labs: teaser")).toBeInTheDocument();
    expect(within(list).getAllByRole("link", { name: /Open report/ })).toHaveLength(2);
  });

  it("builds one for any website, with the name and competitors typed in", async () => {
    let built = false;
    const calls = mockApi({
      ...SIGNED_IN,
      [LIST]: {
        body: () =>
          built
            ? [
                magnet({
                  company_id: null,
                  title: "Acme: teaser",
                  status: "running",
                  step: "reading their posts",
                  link: null,
                  summary: null,
                }),
              ]
            : [],
      },
      "POST /api/magnets": {
        status: 202,
        body: () => {
          built = true;
          return magnet({ company_id: null, title: "Acme: teaser", status: "running", link: null, summary: null });
        },
      },
    });
    renderApp(<MagnetsPage />);
    const user = userEvent.setup();

    expect(await screen.findByText("No lead magnets yet")).toBeInTheDocument();
    const teaser = screen.getByRole("button", { name: "Build a teaser" });
    expect(teaser).toBeDisabled(); // a website first
    await user.type(screen.getByLabelText("Their website"), "acme.example");
    await user.type(screen.getByLabelText(/Company name/), "Acme");
    await user.type(screen.getByLabelText(/Competitors you know/), "rival.example");
    await user.click(teaser);

    await waitFor(() => expect(calls.some((c) => c.method === "POST")).toBe(true));
    expect(calls.find((c) => c.method === "POST")?.body).toEqual({
      mode: "teaser",
      website: "acme.example",
      name: "Acme",
      competitors: ["rival.example"],
    });
    expect(await screen.findByText("Building: reading their posts")).toBeInTheDocument();
    // one build at a time for websites outside the tracker
    expect(screen.getByRole("button", { name: "Build a teaser" })).toBeDisabled();
  });

  it("says what's wrong with a competitor typed in, and sends nothing", async () => {
    const calls = mockApi({ ...SIGNED_IN, [LIST]: { body: [] } });
    renderApp(<MagnetsPage />);
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("Their website"), "acme.example");
    await user.type(screen.getByLabelText(/Competitors you know/), "not a site");
    await user.tab();
    expect(await screen.findByText(/doesn't look like a website/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Build a teaser" })).toBeDisabled();
    expect(calls.some((c) => c.method === "POST")).toBe(false);
  });
});
