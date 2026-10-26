import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { App } from "@/App";
import { STATS, TODAY } from "@/test/fixtures";
import { mockApi, renderApp } from "@/test/render";

describe("signing in", () => {
  it("sends signed-out visitors to the login page", async () => {
    mockApi({ "GET /api/auth/me": { body: { signed_in: false, csrf: null } } });
    renderApp(<App />);
    expect(await screen.findByLabelText("Password")).toBeInTheDocument();
  });

  it("shows the server's message when the password is wrong", async () => {
    mockApi({
      "GET /api/auth/me": { body: { signed_in: false, csrf: null } },
      "POST /api/auth/login": { status: 401, body: { detail: "That password isn't right." } },
    });
    renderApp(<App />, { path: "/login" });
    await userEvent.type(await screen.findByLabelText("Password"), "nope");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("That password isn't right.");
  });

  it("opens Today after signing in, and sends the CSRF token on changes", async () => {
    const calls = mockApi({
      "GET /api/auth/me": { body: { signed_in: false, csrf: null } },
      "POST /api/auth/login": { body: { signed_in: true, csrf: "tok123" } },
      "POST /api/auth/logout": { body: { signed_in: false, csrf: null } },
      "GET /api/stats": { body: STATS },
      "GET /api/today": {
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
      },
    });
    renderApp(<App />, { path: "/login" });
    await userEvent.type(await screen.findByLabelText("Password"), "right password");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("heading", { name: /You're clear/ })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Sign out" }));
    const logout = calls.find((c) => c.path === "/api/auth/logout");
    expect(logout?.headers.get("X-CSRF-Token")).toBe("tok123");
  });

  it("says when the server can't be reached instead of asking to sign in", async () => {
    mockApi({ "GET /api/auth/me": { status: 503, body: { detail: "down" } } });
    renderApp(<App />);
    expect(await screen.findByText("Can't reach the tracker")).toBeInTheDocument();
    expect(screen.queryByLabelText("Password")).not.toBeInTheDocument();
  });

  it("says when signing out fails", async () => {
    mockApi({
      "GET /api/auth/me": { body: { signed_in: true, csrf: "tok" } },
      "POST /api/auth/logout": { status: 503, body: { detail: "down" } },
    });
    renderApp(<App />);
    await userEvent.click(await screen.findByRole("button", { name: "Sign out" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Couldn't sign out");
  });
});
