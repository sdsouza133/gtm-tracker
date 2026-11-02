import { QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter } from "react-router-dom";

import { AuthProvider } from "@/auth";
import { makeQueryClient } from "@/queryClient";

type Route = { status?: number; body: unknown; headers?: Record<string, string> };

/** Stubs fetch with a map of "METHOD /path" to responses, and records every request. A body that's a function is
 * called on each request, for a response that changes after some other call; one that returns a promise holds the
 * response until it settles. */
export function mockApi(routes: Record<string, Route>) {
  const calls: { method: string; path: string; search: URLSearchParams; body: unknown; headers: Headers }[] = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const request = input as Request;
    const url = new URL(request.url);
    const path = url.pathname;
    const text = request.method === "GET" ? "" : await request.text();
    calls.push({
      method: request.method,
      path,
      search: url.searchParams,
      body: text ? JSON.parse(text) : undefined,
      headers: request.headers,
    });
    const route = routes[`${request.method} ${path}`];
    if (!route) return new Response(JSON.stringify({ detail: "Not found" }), { status: 404 });
    const body: unknown = typeof route.body === "function" ? await (route.body as () => unknown)() : route.body;
    return new Response(JSON.stringify(body), {
      status: route.status ?? 200,
      headers: { "Content-Type": "application/json", ...route.headers },
    });
  });
  return calls;
}

export function renderApp(ui: ReactElement, { path = "/" } = {}) {
  const client = makeQueryClient({ retry: false });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <AuthProvider>{ui}</AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}
