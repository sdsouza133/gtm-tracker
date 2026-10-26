import { useState, type FormEvent } from "react";
import { Navigate } from "react-router-dom";

import { ApiError } from "@/api/client";
import { useAuth } from "@/auth";
import { Button } from "@/components/ui";

export function LoginPage() {
  const { signedIn, login } = useAuth();
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (signedIn) return <Navigate to="/" replace />;

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(password);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't sign in. Check your connection and try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="flex min-h-screen items-center justify-center px-4">
      <form onSubmit={submit} className="w-full max-w-sm rounded-card border border-line bg-surface p-8" noValidate>
        <div className="mb-6 flex items-center gap-3">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-ink text-sm font-bold text-white">
            G
          </div>
          <h1 className="text-lg font-semibold">GTM Tracker</h1>
        </div>
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
        {error && (
          <p id="login-error" role="alert" className="mb-3 text-sm font-medium text-bad">
            {error}
          </p>
        )}
        <Button type="submit" variant="primary" className="w-full" disabled={busy || !password}>
          {busy ? "Signing in…" : "Sign in"}
        </Button>
      </form>
    </main>
  );
}
