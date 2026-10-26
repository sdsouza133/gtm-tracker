import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { App } from "@/App";
import { SIGNED_IN, STATS } from "@/test/fixtures";
import { mockApi, renderApp } from "@/test/render";

const TODAY_PAGE = { "GET /api/stats": { body: STATS }, "GET /api/today": { status: 503, body: { detail: "x" } } };

describe("Download backup", () => {
  it("saves the file under the server's name", async () => {
    const save = vi.fn();
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
      save(this.download);
    });
    URL.createObjectURL = vi.fn(() => "blob:backup");
    URL.revokeObjectURL = vi.fn();
    mockApi({
      ...SIGNED_IN,
      ...TODAY_PAGE,
      "GET /api/export": {
        body: { version: 1 },
        headers: { "Content-Disposition": 'attachment; filename="gtm-tracker-2026-10-26.json"' },
      },
    });
    renderApp(<App />, { path: "/" });
    await userEvent.click(await screen.findByRole("button", { name: "Download backup" }));
    await waitFor(() => expect(save).toHaveBeenCalledWith("gtm-tracker-2026-10-26.json"));
  });

  it("shows the sign-in page when the session has lapsed, instead of saving an error", async () => {
    URL.createObjectURL = vi.fn(() => "blob:backup");
    mockApi({ ...SIGNED_IN, ...TODAY_PAGE, "GET /api/export": { status: 401, body: { detail: "Sign in first" } } });
    renderApp(<App />, { path: "/" });
    await userEvent.click(await screen.findByRole("button", { name: "Download backup" }));
    expect(await screen.findByRole("button", { name: "Sign in" })).toBeInTheDocument();
    expect(URL.createObjectURL).not.toHaveBeenCalled();
  });
});

describe("Open access", () => {
  it("has no sign-out button when the server runs without a login", async () => {
    mockApi({ "GET /api/auth/me": { body: { signed_in: true, csrf: null, open_access: true } }, ...TODAY_PAGE });
    renderApp(<App />, { path: "/" });
    expect(await screen.findByRole("button", { name: "Download backup" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Sign out" })).not.toBeInTheDocument();
  });
});
