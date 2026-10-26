import type { ReactNode } from "react";
import { Navigate, Route, Routes } from "react-router-dom";

import { useAuth } from "@/auth";
import { Layout } from "@/components/Layout";
import { EmptyState, PageHeader } from "@/components/ui";
import { LoginPage } from "@/pages/Login";

function RequireAuth({ children }: { children: ReactNode }) {
  const { signedIn, loading } = useAuth();
  if (loading) return <p className="p-8 text-sm text-muted">Loading…</p>;
  if (!signedIn) return <Navigate to="/login" replace />;
  return <>{children}</>;
}

function Placeholder({ title }: { title: string }) {
  return (
    <div className="flex max-w-6xl flex-col gap-6">
      <PageHeader title={title} />
      <EmptyState title="Coming in the next pull request" />
    </div>
  );
}

export function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        element={
          <RequireAuth>
            <Layout />
          </RequireAuth>
        }
      >
        <Route index element={<Placeholder title="Today" />} />
        <Route path="pipeline" element={<Placeholder title="Pipeline" />} />
        <Route path="people" element={<Placeholder title="People" />} />
        <Route path="plan" element={<Placeholder title="Plan" />} />
        <Route path="radar" element={<Placeholder title="Radar" />} />
        <Route path="fractional" element={<Placeholder title="Fractional" />} />
        <Route path="*" element={<Placeholder title="Not found" />} />
      </Route>
    </Routes>
  );
}
