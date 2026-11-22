import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { Magnet } from "@/api/hooks";
import { MagnetsPage } from "@/pages/Magnets";
import { championsMagnet, SIGNED_IN } from "@/test/fixtures";
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
    domain: "northwind.example",
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
      kind: "engagement",
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

  it("builds a champion report for any website, asking for no competitors", async () => {
    let built = false;
    const calls = mockApi({
      ...SIGNED_IN,
      [LIST]: {
        body: () =>
          built
            ? [
                championsMagnet({
                  status: "running",
                  step: "looking for people who left them",
                  link: null,
                  champions: null,
                }),
              ]
            : [],
      },
      "POST /api/magnets": {
        status: 202,
        body: () => {
          built = true;
          return championsMagnet({ status: "running", step: "starting", link: null, champions: null });
        },
      },
    });
    renderApp(<MagnetsPage />);
    const user = userEvent.setup();

    await user.click(await screen.findByRole("radio", { name: "Champions who moved" }));
    expect(screen.queryByLabelText(/Competitors you know/)).not.toBeInTheDocument();
    const build = screen.getByRole("button", { name: "Build the champion report" });
    expect(build).toBeDisabled(); // a website first
    await user.type(screen.getByLabelText("Their website"), "cxhero.example");
    await user.type(screen.getByLabelText(/Company name/), "CXHero");
    await user.click(build);

    await waitFor(() => expect(calls.some((c) => c.method === "POST")).toBe(true));
    expect(calls.find((c) => c.method === "POST")?.body).toEqual({
      kind: "champions",
      website: "cxhero.example",
      name: "CXHero",
    });
    expect(await screen.findByText("Building: looking for people who left them")).toBeInTheDocument();
    // one champion report at a time
    expect(screen.getByRole("button", { name: "Build the champion report" })).toBeDisabled();
    // an engagement magnet for a website outside the tracker can still start
    await user.click(screen.getByRole("radio", { name: "Engagers" }));
    expect(screen.getByRole("button", { name: "Build a teaser" })).toBeEnabled();
  });

  it("shows a champion report's result and opens its full report", async () => {
    mockApi({ ...SIGNED_IN, [LIST]: { body: [championsMagnet()] } });
    renderApp(<MagnetsPage />);
    expect(await screen.findByText("4 champions moved (2 A, 1 B, 1 C)")).toBeInTheDocument();
    expect(
      screen.getByText(/4 of 5 customers found on LinkedIn · 20 left them in the last 90 days/),
    ).toBeInTheDocument();
    expect(screen.queryByText(/new since the last report/)).not.toBeInTheDocument(); // a first report
    expect(screen.getByRole("link", { name: /Full report/ })).toHaveAttribute("href", "/magnets/m1");
    expect(screen.getByRole("link", { name: /Open report/ })).toHaveAttribute("href", "/m/m1/tok");
  });

  it("says why a champion report couldn't start", async () => {
    mockApi({
      ...SIGNED_IN,
      [LIST]: { body: [] },
      "POST /api/magnets": {
        status: 409,
        body: { detail: "Today's champion reports have used $3.00 of the $3.00 daily limit. Try again tomorrow." },
      },
    });
    renderApp(<MagnetsPage />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("radio", { name: "Champions who moved" }));
    await user.type(screen.getByLabelText("Their website"), "cxhero.example");
    await user.click(screen.getByRole("button", { name: "Build the champion report" }));
    expect(await screen.findByText(/daily limit\. Try again tomorrow\./)).toBeInTheDocument();
  });
});
