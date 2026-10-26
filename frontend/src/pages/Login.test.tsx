import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { App } from "@/App";
import { STATS, TODAY } from "@/test/fixtures";
import { mockApi, renderApp } from "@/test/render";

const SIGNED_OUT = { body: { signed_in: false, csrf: null, password_login: true } };
const CLIENT_ID = "test-client.apps.googleusercontent.com";
const GOOGLE_ONLY = { body: { signed_in: false, csrf: null, google_client_id: CLIENT_ID, password_login: false } };

/** Stands in for Google's script: renders a plain button that hands back the given ID token when clicked. */
function fakeGoogle(credential: string) {
  const initialize = vi.fn();
  window.google = {
    accounts: {
      id: {
        initialize,
        renderButton: (parent) => {
          const button = document.createElement("button");
          button.textContent = "Sign in with Google";
          button.onclick = () => initialize.mock.calls[0]?.[0].callback({ credential });
          parent.append(button);
        },
      },
    },
  };
  return initialize;
}

afterEach(() => {
  delete window.google;
});

describe("signing in", () => {
  it("sends signed-out visitors to the login page", async () => {
    mockApi({ "GET /api/auth/me": SIGNED_OUT });
    renderApp(<App />);
    expect(await screen.findByLabelText("Password")).toBeInTheDocument();
  });

  it("shows the server's message when the password is wrong", async () => {
    mockApi({
      "GET /api/auth/me": SIGNED_OUT,
      "POST /api/auth/login": { status: 401, body: { detail: "That password isn't right." } },
    });
    renderApp(<App />, { path: "/login" });
    await userEvent.type(await screen.findByLabelText("Password"), "nope");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("That password isn't right.");
  });

  it("opens Today after signing in, and sends the CSRF token on changes", async () => {
    const calls = mockApi({
      "GET /api/auth/me": SIGNED_OUT,
      "POST /api/auth/login": { body: { signed_in: true, csrf: "tok123" } },
      "POST /api/auth/logout": SIGNED_OUT,
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
    expect(await screen.findByLabelText("Password")).toBeInTheDocument(); // back to the sign-in page, form and all
  });

  it("says when the server can't be reached instead of asking to sign in", async () => {
    mockApi({ "GET /api/auth/me": { status: 503, body: { detail: "down" } } });
    renderApp(<App />);
    expect(await screen.findByText("Can't reach the tracker")).toBeInTheDocument();
    expect(screen.queryByLabelText("Password")).not.toBeInTheDocument();
  });

  it("shows Google's button, and no password form, when only Google sign-in is set up", async () => {
    mockApi({ "GET /api/auth/me": GOOGLE_ONLY });
    renderApp(<App />, { path: "/login" });
    expect(await screen.findByTestId("google-button")).toBeInTheDocument();
    expect(screen.queryByLabelText("Password")).not.toBeInTheDocument();
  });

  it("offers both when Google and a password are set up", async () => {
    mockApi({ "GET /api/auth/me": { body: { ...GOOGLE_ONLY.body, password_login: true } } });
    renderApp(<App />, { path: "/login" });
    expect(await screen.findByTestId("google-button")).toBeInTheDocument();
    expect(screen.getByLabelText("Password")).toBeInTheDocument();
  });

  it("signs in with Google and opens Today", async () => {
    const initialize = fakeGoogle("google-id-token");
    const calls = mockApi({
      "GET /api/auth/me": GOOGLE_ONLY,
      "POST /api/auth/google": { body: { signed_in: true, csrf: "tok123", google_client_id: CLIENT_ID } },
      "GET /api/stats": { body: STATS },
      "GET /api/today": {
        body: { today: TODAY, groups: [], overdue: 0, more: 0, done_today: [], waiting: [], waiting_total: 0 },
      },
    });
    renderApp(<App />, { path: "/login" });
    await userEvent.click(await screen.findByRole("button", { name: "Sign in with Google" }));
    expect(await screen.findByRole("heading", { name: /You're clear/ })).toBeInTheDocument();
    expect(initialize).toHaveBeenCalledWith(expect.objectContaining({ client_id: CLIENT_ID }));
    expect(calls.find((c) => c.path === "/api/auth/google")?.body).toEqual({ credential: "google-id-token" });
  });

  it("says so when the Google account isn't allowed", async () => {
    fakeGoogle("someone-elses-token");
    mockApi({
      "GET /api/auth/me": GOOGLE_ONLY,
      "POST /api/auth/google": {
        status: 401,
        body: { detail: "stranger@example.com isn't allowed to sign in here." },
      },
    });
    renderApp(<App />, { path: "/login" });
    await userEvent.click(await screen.findByRole("button", { name: "Sign in with Google" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("stranger@example.com isn't allowed to sign in here.");
  });

  it("says how to set sign-in up when there's no way in", async () => {
    mockApi({ "GET /api/auth/me": { body: { signed_in: false, csrf: null } } });
    renderApp(<App />, { path: "/login" });
    expect(await screen.findByText(/Sign-in isn't set up yet/)).toBeInTheDocument();
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
