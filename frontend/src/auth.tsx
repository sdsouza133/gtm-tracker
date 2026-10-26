import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createContext, useContext, type ReactNode } from "react";

import { api, setCsrfToken, unwrap } from "@/api/client";
import type { components } from "@/api/schema";

type Me = components["schemas"]["Me"];

type Auth = {
  signedIn: boolean;
  /** The server runs without a login (OPEN_ACCESS): nothing to sign out of. */
  openAccess: boolean;
  /** Set when Google sign-in is set up: the sign-in page shows Google's button for this client. */
  googleClientId: string | null;
  /** A password is set, so the sign-in page shows the password form too. */
  passwordLogin: boolean;
  loading: boolean;
  /** The server couldn't say who's signed in (down, or the network dropped). */
  failed: boolean;
  retry: () => void;
  login: (password: string) => Promise<void>;
  /** Signs in with the ID token Google's button handed back. */
  googleLogin: (credential: string) => Promise<void>;
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
  const signedIn = (data: Me) => {
    setCsrfToken(data.csrf ?? null);
    client.setQueryData(["me"], data);
  };
  const loginMutation = useMutation({
    meta: { quiet: true },
    mutationFn: async (password: string) => unwrap(await api.POST("/api/auth/login", { body: { password } })),
    onSuccess: signedIn,
  });
  const googleMutation = useMutation({
    meta: { quiet: true }, // the sign-in page shows its own message
    mutationFn: async (credential: string) => unwrap(await api.POST("/api/auth/google", { body: { credential } })),
    onSuccess: signedIn,
  });
  const logoutMutation = useMutation({
    meta: { quiet: true }, // the layout shows its own message
    mutationFn: async () => unwrap(await api.POST("/api/auth/logout")),
    onSuccess: (data) => {
      setCsrfToken(null);
      client.clear();
      client.setQueryData(["me"], data);
    },
  });
  const value: Auth = {
    signedIn: me.data?.signed_in ?? false,
    openAccess: me.data?.open_access ?? false,
    googleClientId: me.data?.google_client_id ?? null,
    passwordLogin: me.data?.password_login ?? false,
    loading: me.isPending,
    failed: me.isError,
    retry: () => void me.refetch(),
    login: async (password) => {
      await loginMutation.mutateAsync(password);
    },
    googleLogin: async (credential) => {
      await googleMutation.mutateAsync(credential);
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
