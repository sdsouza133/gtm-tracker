import createClient, { type Middleware } from "openapi-fetch";

import type { paths } from "./schema";

let csrfToken: string | null = null;

/** The session's CSRF token, sent on every change. The server hands it out at sign-in and from /api/auth/me. */
export function setCsrfToken(token: string | null): void {
  csrfToken = token;
}

const SAFE = new Set(["GET", "HEAD", "OPTIONS"]);

const csrf: Middleware = {
  onRequest({ request }) {
    if (csrfToken && !SAFE.has(request.method)) request.headers.set("X-CSRF-Token", csrfToken);
    return request;
  },
};

export const api = createClient<paths>({
  baseUrl: window.location.origin,
  credentials: "same-origin",
  // looked up per call, so tests (and polyfills) can replace fetch after this module loads
  fetch: (request) => globalThis.fetch(request),
});
api.use(csrf);

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

/** Unwraps an openapi-fetch result: the data, or an ApiError with the server's message. */
export function unwrap<T>(result: { data?: T; error?: unknown; response: Response }): T {
  if (result.error !== undefined || result.data === undefined) {
    const detail = (result.error as { detail?: unknown } | undefined)?.detail;
    const message = typeof detail === "string" ? detail : "Something went wrong. Try again.";
    throw new ApiError(result.response.status, message);
  }
  return result.data;
}
