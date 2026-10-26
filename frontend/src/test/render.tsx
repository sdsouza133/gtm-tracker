import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter } from "react-router-dom";

import { AuthProvider } from "@/auth";

type Route = { status?: number; body: unknown };

/** Stubs fetch with a map of "METHOD /path" to responses, and records every request. */
export function mockApi(routes: Record<string, Route>) {
  const calls: { method: string; path: string; body: unknown; headers: Headers }[] = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const request = input as Request;
    const path = new URL(request.url).pathname;
    const text = request.method === "GET" ? "" : await request.text();
    calls.push({ method: request.method, path, body: text ? JSON.parse(text) : undefined, headers: request.headers });
    const route = routes[`${request.method} ${path}`];
    if (!route) return new Response(JSON.stringify({ detail: "Not found" }), { status: 404 });
    return new Response(JSON.stringify(route.body), {
      status: route.status ?? 200,
      headers: { "Content-Type": "application/json" },
    });
  });
  return calls;
}

export function renderApp(ui: ReactElement, { path = "/" } = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <AuthProvider>{ui}</AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}
