import { useState, type FormEvent } from "react";
import { Navigate } from "react-router-dom";

import { ApiError } from "@/api/client";
import { useAuth } from "@/auth";
import { GoogleButton } from "@/components/GoogleButton";
import { Button } from "@/components/ui";

const OFFLINE = "Couldn't sign in. Check your connection and try again.";

export function LoginPage() {
  const { signedIn, login, googleLogin, googleClientId, passwordLogin } = useAuth();
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (signedIn) return <Navigate to="/" replace />;

  async function attempt(signIn: () => Promise<void>) {
    setBusy(true);
    setError(null);
    try {
      await signIn();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : OFFLINE);
    } finally {
      setBusy(false);
    }
  }

  function submit(e: FormEvent) {
    e.preventDefault();
    void attempt(() => login(password));
  }

  const errorText = error && (
    <p id="login-error" role="alert" className="mb-3 text-sm font-medium text-bad">
      {error}
    </p>
  );

  return (
    <main className="flex min-h-screen items-center justify-center px-4">
      <div className="w-full max-w-sm rounded-card border border-line bg-surface p-8">
        <div className="mb-6 flex items-center gap-3">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-ink text-sm font-bold text-white">
            G
          </div>
          <h1 className="text-lg font-semibold">GTM Tracker</h1>
        </div>
        {googleClientId && (
          <>
            <GoogleButton
              clientId={googleClientId}
              onCredential={(credential) => void attempt(() => googleLogin(credential))}
            />
            {busy && !passwordLogin && <p className="mt-3 text-center text-sm text-muted">Signing in…</p>}
            {!passwordLogin && <div className="mt-3">{errorText}</div>}
          </>
        )}
        {googleClientId && passwordLogin && (
          <p className="my-5 flex items-center gap-3 text-xs text-muted before:h-px before:flex-1 before:bg-line after:h-px after:flex-1 after:bg-line">
            or
          </p>
        )}
        {passwordLogin && (
          <form onSubmit={submit} noValidate>
            <label htmlFor="password" className="mb-1 block text-sm font-medium">
              Password
            </label>
            <input
              id="password"
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              aria-invalid={error ? true : undefined}
              aria-describedby={error ? "login-error" : undefined}
              className="mb-3 block min-h-[42px] w-full rounded-lg border border-field px-3 text-sm"
            />
            {errorText}
            <Button type="submit" variant="primary" className="w-full" disabled={busy || !password}>
              {busy ? "Signing in…" : "Sign in"}
            </Button>
          </form>
        )}
        {!googleClientId && !passwordLogin && (
          <p className="text-sm text-muted">
            Sign-in isn't set up yet. Set GOOGLE_CLIENT_ID and ALLOWED_EMAILS (or PASSWORD_HASH) on the server.
          </p>
        )}
      </div>
    </main>
  );
}
