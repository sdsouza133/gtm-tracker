import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createContext, useContext, type ReactNode } from "react";

import { api, setCsrfToken, unwrap } from "@/api/client";

type Auth = {
  signedIn: boolean;
  loading: boolean;
  /** The server couldn't say who's signed in (down, or the network dropped). */
  failed: boolean;
  retry: () => void;
  login: (password: string) => Promise<void>;
  logout: () => Promise<void>;
};

const AuthContext = createContext<Auth | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const client = useQueryClient();
  const me = useQuery({
    queryKey: ["me"],
    queryFn: async () => {
      const data = unwrap(await api.GET("/api/auth/me"));
      setCsrfToken(data.csrf ?? null);
      return data;
    },
    staleTime: Infinity,
  });
  const loginMutation = useMutation({
    mutationFn: async (password: string) => unwrap(await api.POST("/api/auth/login", { body: { password } })),
    onSuccess: (data) => {
      setCsrfToken(data.csrf ?? null);
      client.setQueryData(["me"], data);
    },
  });
  const logoutMutation = useMutation({
    mutationFn: async () => unwrap(await api.POST("/api/auth/logout")),
    onSuccess: () => {
      setCsrfToken(null);
      client.clear();
      client.setQueryData(["me"], { signed_in: false, csrf: null });
    },
  });
  const value: Auth = {
    signedIn: me.data?.signed_in ?? false,
    loading: me.isPending,
    failed: me.isError,
    retry: () => void me.refetch(),
    login: async (password) => {
      await loginMutation.mutateAsync(password);
    },
    logout: async () => {
      await logoutMutation.mutateAsync();
    },
  };
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): Auth {
  const auth = useContext(AuthContext);
  if (!auth) throw new Error("useAuth must be used inside AuthProvider");
  return auth;
}
