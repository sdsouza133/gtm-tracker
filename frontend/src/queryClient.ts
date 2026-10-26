import { MutationCache, QueryCache, QueryClient } from "@tanstack/react-query";

import { ApiError } from "@/api/client";
import { notify } from "@/components/Toast";

export function makeQueryClient({ retry = true } = {}): QueryClient {
  const client: QueryClient = new QueryClient({
    // a 401 anywhere means the session ended (expired, or signed out elsewhere): show the sign-in page
    queryCache: new QueryCache({
      onError: (error, query) => {
        if (error instanceof ApiError && error.status === 401 && query.queryKey[0] !== "me") {
          client.setQueryData(["me"], { signed_in: false, csrf: null });
        }
      },
    }),
    // every failed change says why, in the server's words when it gave some
    mutationCache: new MutationCache({
      onError: (error, _vars, _context, mutation) => {
        if (mutation.meta?.["quiet"]) return; // the form shows its own message
        if (error instanceof ApiError && error.status === 401) {
          client.setQueryData(["me"], { signed_in: false, csrf: null });
          return;
        }
        notify(error instanceof ApiError ? error.message : "Couldn't save that. Try again.", "error");
      },
    }),
    defaultOptions: {
      queries: {
        staleTime: 30_000,
        retry: retry ? (count, error) => !(error instanceof ApiError && error.status < 500) && count < 2 : false,
      },
    },
  });
  return client;
}
