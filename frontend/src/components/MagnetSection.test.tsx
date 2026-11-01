import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { Magnet } from "@/api/hooks";
import { MagnetSection } from "@/components/MagnetSection";
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
    summary: { leads: 3, hot: 1, warm: 2, touch: 0, emails: 0, fit: 9, people: 40, apify_usd: 0.21 },
    ...over,
  };
}

const LIST = "GET /api/companies/c1/magnets";

describe("the lead magnet section", () => {
  it("builds a teaser from the company's website and the competitors typed in", async () => {
    let built = false;
    const calls = mockApi({
      ...SIGNED_IN,
      [LIST]: {
        body: () =>
          built ? [magnet({ status: "running", step: "reading their posts", link: null, summary: null })] : [],
      },
      "POST /api/companies/c1/magnets": {
        status: 202,
        body: () => {
          built = true;
          return magnet({ status: "running", link: null, summary: null });
        },
      },
    });
    renderApp(<MagnetSection companyId="c1" website="https://northwind.example" />);
    const user = userEvent.setup();

    expect(screen.getByLabelText("Their website")).toHaveValue("https://northwind.example");
    await user.type(screen.getByLabelText(/Competitors you know/), "rival.example, other.example");
    await user.click(screen.getByRole("button", { name: "Build a teaser" }));

    await waitFor(() => expect(calls.some((c) => c.method === "POST")).toBe(true));
    expect(calls.find((c) => c.method === "POST")?.body).toEqual({
      mode: "teaser",
      website: "https://northwind.example",
      competitors: ["rival.example", "other.example"],
    });
    expect(await screen.findByText("Building: reading their posts")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Build the full list" })).toBeDisabled(); // one at a time
  });

  it("shows a finished one with its counts and link, and a failed one with why", async () => {
    mockApi({
      ...SIGNED_IN,
      [LIST]: {
        body: [
          magnet(),
          magnet({
            id: "g2",
            status: "failed",
            error: "None of the competitors has a LinkedIn page.",
            link: null,
            summary: null,
          }),
        ],
      },
    });
    renderApp(<MagnetSection companyId="c1" website="northwind.example" />);

    expect(
      await screen.findByText(/3 in the US or Canada \(1 hot, 2 warm, 0 single touch\) out of 9/),
    ).toBeInTheDocument();
    expect(screen.getByText(/Opened 2 times/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Open report/ })).toHaveAttribute("href", "/m/g1/tok");
    expect(screen.getByRole("button", { name: /Copy link/ })).toBeInTheDocument();
    expect(screen.getAllByText("Ready")[0]?.closest("[aria-live]")).toHaveAttribute("aria-live", "polite");
    expect(screen.getByText("None of the competitors has a LinkedIn page.")).toBeInTheDocument();
  });

  it("deletes one, turning its link off", async () => {
    const calls = mockApi({
      ...SIGNED_IN,
      [LIST]: { body: [magnet()] },
      "DELETE /api/magnets/g1": { status: 204, body: null },
    });
    renderApp(<MagnetSection companyId="c1" website="northwind.example" />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: /^Delete Teaser, .+ and turn its link off$/ }));
    await waitFor(() => expect(calls.some((c) => c.method === "DELETE" && c.path === "/api/magnets/g1")).toBe(true));
  });

  it("says which competitor isn't a website instead of sending it", async () => {
    const calls = mockApi({ ...SIGNED_IN, [LIST]: { body: [] } });
    renderApp(<MagnetSection companyId="c1" website="northwind.example" />);
    const user = userEvent.setup();
    const field = screen.getByLabelText(/Competitors you know/);
    await user.type(field, "rival.example, a");
    expect(screen.queryByText(/doesn't look like a website/)).not.toBeInTheDocument(); // not while typing
    await user.tab();
    expect(
      screen.getByText("\"a\" doesn't look like a website. Type competitors' domains, like rival.com."),
    ).toHaveAttribute("aria-live", "polite");
    expect(field).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByRole("button", { name: "Build a teaser" })).toBeDisabled();
    expect(calls.some((c) => c.method === "POST")).toBe(false);
  });

  it("takes competitor links with a query string or a path", async () => {
    mockApi({ ...SIGNED_IN, [LIST]: { body: [] } });
    renderApp(<MagnetSection companyId="c1" website="northwind.example" />);
    const user = userEvent.setup();
    await user.type(
      screen.getByLabelText(/Competitors you know/),
      "https://rival.example?ref=share, other.example/pricing",
    );
    await user.tab();
    expect(screen.getByRole("button", { name: "Build a teaser" })).toBeEnabled();
  });

  it("can't build without a website", async () => {
    mockApi({ ...SIGNED_IN, [LIST]: { body: [] } });
    renderApp(<MagnetSection companyId="c1" website="" />);
    expect(screen.getByRole("button", { name: "Build a teaser" })).toBeDisabled();
  });
});
