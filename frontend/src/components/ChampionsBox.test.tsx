import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { ChampionsBox } from "@/components/ChampionsBox";
import { championsMagnet, championsSummary, SIGNED_IN } from "@/test/fixtures";
import { mockApi, renderApp } from "@/test/render";

const LIST = "GET /api/magnets";

describe("the champion report on a company's card", () => {
  it("builds one for the company's website and follows it", async () => {
    let built = false;
    const calls = mockApi({
      ...SIGNED_IN,
      [LIST]: {
        body: () =>
          built
            ? [
                championsMagnet({
                  status: "running",
                  step: "finding the customers on LinkedIn",
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
    renderApp(<ChampionsBox name="CXHero" website="https://www.cxhero.example/" />);
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: /Build the champion report/ }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST")).toBe(true));
    expect(calls.find((c) => c.method === "POST")?.body).toEqual({
      kind: "champions",
      website: "https://www.cxhero.example/",
      name: "CXHero",
    });
    expect(await screen.findByText("Building: finding the customers on LinkedIn")).toBeInTheDocument();
    const listed = calls.find((c) => c.method === "GET" && c.path === "/api/magnets");
    expect(listed?.search.get("kind")).toBe("champions");
    expect(listed?.search.get("domain")).toBe("cxhero.example");
  });

  it("shows the latest result with its links, and builds it again", async () => {
    const calls = mockApi({
      ...SIGNED_IN,
      [LIST]: {
        body: [
          championsMagnet({ champions: championsSummary({ repeat: true, new: 1 }) }),
          championsMagnet({ id: "m0" }),
        ],
      },
      "POST /api/magnets": { status: 202, body: championsMagnet({ status: "running", link: null, champions: null }) },
    });
    renderApp(<ChampionsBox name="CXHero" website="cxhero.example" />);
    const user = userEvent.setup();

    expect(await screen.findByText("4 champions moved (2 A, 1 B, 1 C)")).toBeInTheDocument();
    expect(screen.getByText(/1 new since the last report/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Open report/ })).toHaveAttribute("href", "/magnets/m1");
    expect(screen.getByRole("button", { name: /Copy link/ })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Build again/ }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST")).toBe(true));
  });

  it("says why the last one didn't finish, and tries again", async () => {
    mockApi({
      ...SIGNED_IN,
      [LIST]: {
        body: [
          championsMagnet({
            status: "failed",
            link: null,
            champions: null,
            error: "The website doesn't show any customers, so there's no one to track.",
          }),
        ],
      },
    });
    renderApp(<ChampionsBox name="CXHero" website="cxhero.example" />);
    expect(await screen.findByText(/doesn't show any customers/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Try again/ })).toBeEnabled();
  });

  it("says it's loading while the reports load", async () => {
    mockApi({ ...SIGNED_IN, [LIST]: { body: () => new Promise(() => {}) } }); // never answers
    renderApp(<ChampionsBox name="CXHero" website="cxhero.example" />);
    expect(await screen.findByRole("status")).toHaveTextContent("Loading…");
    expect(screen.queryByRole("button", { name: /Build the champion report/ })).not.toBeInTheDocument();
  });

  it("shows nothing for a company with no website", () => {
    const calls = mockApi({ ...SIGNED_IN });
    renderApp(<ChampionsBox name="CXHero" website={null} />);
    expect(screen.queryByRole("region", { name: "Champion report" })).not.toBeInTheDocument();
    expect(calls.some((c) => c.path === "/api/magnets")).toBe(false);
  });
});
