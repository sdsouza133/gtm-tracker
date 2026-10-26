import { MutationCache, QueryClient } from "@tanstack/react-query";

import { ApiError } from "@/api/client";
import { notify } from "@/components/Toast";

export function makeQueryClient({ retry = true } = {}): QueryClient {
  return new QueryClient({
    // every failed change says why, in the server's words when it gave some
    mutationCache: new MutationCache({
      onError: (error, _vars, _context, mutation) => {
        if (mutation.meta?.["quiet"]) return; // the form shows its own message
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
}
