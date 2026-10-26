import { clsx } from "clsx";
import { CalendarDays, Columns3, Download, LogOut, Radar, Sparkles, Sun, Users } from "lucide-react";
import { useState } from "react";
import { NavLink, Outlet } from "react-router-dom";

import { useAuth } from "@/auth";

const NAV = [
  { to: "/", label: "Today", icon: Sun, end: true },
  { to: "/pipeline", label: "Pipeline", icon: Columns3 },
  { to: "/people", label: "People", icon: Users },
  { to: "/plan", label: "Plan", icon: CalendarDays },
  { to: "/radar", label: "Radar", icon: Radar },
  { to: "/fractional", label: "Fractional", icon: Sparkles },
];

export function Layout() {
  const { logout } = useAuth();
  const [signOutFailed, setSignOutFailed] = useState(false);
  const signOut = () => {
    setSignOutFailed(false);
    logout().catch(() => setSignOutFailed(true));
  };
  return (
    <div className="flex min-h-screen flex-wrap">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4">
        Skip to content
      </a>
      <nav
        aria-label="Main"
        className="flex w-full flex-col gap-1 border-b border-line bg-surface px-3 py-4 md:min-h-screen md:w-60 md:border-b-0 md:border-r"
      >
        <div className="flex items-center gap-2.5 px-2 pb-4">
          <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-ink text-[13px] font-bold text-white">
            G
          </div>
          <span className="text-[15px] font-semibold">GTM Tracker</span>
        </div>
        <div className="flex flex-wrap gap-1 md:flex-col">
          {NAV.map(({ to, label, icon: Icon, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              className={({ isActive }) =>
                clsx(
                  "flex min-h-[40px] items-center gap-2.5 rounded-lg px-2.5 text-sm",
                  isActive ? "bg-accent-tint font-semibold text-accent-ink" : "font-medium text-ink hover:bg-chip",
                )
              }
            >
              <Icon size={16} aria-hidden="true" />
              {label}
            </NavLink>
          ))}
        </div>
        <a
          href="/api/export"
          download
          className="flex min-h-[40px] w-fit items-center gap-2.5 rounded-lg px-2.5 text-sm font-medium text-muted hover:bg-chip hover:text-ink md:mt-auto md:w-auto"
        >
          <Download size={16} aria-hidden="true" />
          Download backup
        </a>
        <button
          type="button"
          onClick={signOut}
          className="flex min-h-[40px] w-fit items-center gap-2.5 rounded-lg px-2.5 text-sm font-medium text-muted hover:bg-chip hover:text-ink md:w-auto"
        >
          <LogOut size={16} aria-hidden="true" />
          Sign out
        </button>
        {signOutFailed && (
          <p role="alert" className="px-2.5 text-[13px] text-bad">
            Couldn't sign out. Check your connection and try again.
          </p>
        )}
      </nav>
      <main id="main" tabIndex={-1} className="min-w-0 flex-1 px-4 pb-12 pt-6 md:px-8 md:pt-7">
        <Outlet />
      </main>
    </div>
  );
}
