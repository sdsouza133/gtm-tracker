import type { ReactNode } from "react";
import { Navigate, Route, Routes } from "react-router-dom";

import { useAuth } from "@/auth";
import { Layout } from "@/components/Layout";
import { Button, EmptyState, PageHeader } from "@/components/ui";
import { CompanyPage } from "@/pages/Company";
import { LoginPage } from "@/pages/Login";
import { PeoplePage } from "@/pages/People";
import { PipelinePage } from "@/pages/Pipeline";
import { PlanPage } from "@/pages/Plan";
import { TodayPage } from "@/pages/Today";

function RequireAuth({ children }: { children: ReactNode }) {
  const { signedIn, loading, failed, retry } = useAuth();
  if (loading) return <p className="p-8 text-sm text-muted">Loading…</p>;
  if (failed)
    return (
      <div className="mx-auto mt-24 max-w-sm px-4">
        <EmptyState title="Can't reach the tracker">
          <p>The server didn't answer. Check your connection, then try again.</p>
          <Button className="mt-4" onClick={retry}>
            Try again
          </Button>
        </EmptyState>
      </div>
    );
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
        <Route index element={<TodayPage />} />
        <Route path="pipeline" element={<PipelinePage />} />
        <Route path="companies/:id" element={<CompanyPage />} />
        <Route path="people" element={<PeoplePage />} />
        <Route path="plan" element={<PlanPage />} />
        <Route path="radar" element={<Placeholder title="Radar" />} />
        <Route path="fractional" element={<Placeholder title="Fractional" />} />
        <Route path="*" element={<Placeholder title="Not found" />} />
      </Route>
    </Routes>
  );
}
