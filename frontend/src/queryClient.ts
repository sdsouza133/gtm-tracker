import { QueryCache, QueryClient } from "@tanstack/react-query";

import { ApiError } from "@/api/client";

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
    defaultOptions: {
      queries: {
        staleTime: 30_000,
        retry: retry ? (count, error) => !(error instanceof ApiError && error.status < 500) && count < 2 : false,
      },
    },
  });
  return client;
}
