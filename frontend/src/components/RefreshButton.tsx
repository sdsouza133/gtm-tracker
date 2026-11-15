import { clsx } from "clsx";
import { RefreshCw } from "lucide-react";
import { useEffect, useRef } from "react";

import { useRadar, useReloadAfterRadar, useRunRadar } from "@/api/hooks";
import { notify } from "@/components/Toast";
import { Button } from "@/components/ui";
import { formatDateTimeDay, formatTime } from "@/lib/format";

type RadarStatus = {
  running?: boolean;
  step?: string;
  last_run_at?: string;
  error?: string;
  summary?: Record<string, number>;
};

/** Refresh everything: a full radar pass (tracked companies' job boards, LinkedIn, company job boards through Google,
 * hiring posts), with the strongest new roles added to the board along with the people to write to. Shows the pass's
 * progress, and reloads the page's lists when it finishes. */
export function RefreshButton() {
  const radar = useRadar();
  const run = useRunRadar();
  const reload = useReloadAfterRadar();
  const s = (radar.data?.status ?? {}) as RadarStatus;
  const running = !!s.running;
  const wasRunning = useRef(running);
  useEffect(() => {
    if (wasRunning.current && !running) void reload(); // it just finished: show what it found
    wasRunning.current = running;
  }, [running, reload]);

  const sm = s.summary ?? {};
  const added = sm["auto_added"] ?? 0;
  const atYours = (sm["tracked_new"] ?? 0) + (sm["linkedin_tracked"] ?? 0);
  let line = "Not refreshed yet";
  if (radar.isPending) line = "Checking when it last ran…";
  else if (radar.isError && !radar.data) line = "Couldn't load when it last ran.";
  else if (running) line = `Refreshing: ${s.step || "starting"}…`;
  else if (s.last_run_at)
    line =
      `Refreshed ${formatDateTimeDay(s.last_run_at)} at ${formatTime(s.last_run_at)}: ` +
      `${added} ${added === 1 ? "company" : "companies"} added, ${sm["people_added"] ?? 0} people, ` +
      `${atYours} new ${atYours === 1 ? "role" : "roles"} at yours`;

  return (
    <div className="flex flex-col items-start gap-1 sm:items-end">
      <Button
        variant="primary"
        disabled={run.isPending || running}
        onClick={() =>
          run.mutate(undefined, {
            onSuccess: () => notify("Refreshing: looking for new roles and the people to write to. About a minute."),
          })
        }
      >
        <RefreshCw size={14} aria-hidden="true" className={clsx(running && "animate-spin")} />
        {running ? "Refreshing…" : "Refresh"}
      </Button>
      {/* one live region that's always there, so the status line and a pass's error are both announced */}
      <div role="status" aria-live="polite" className="flex flex-col items-start gap-1 sm:items-end">
        <p className="text-[12px] text-muted">
          {line}
          {radar.isError && !radar.data && (
            <button type="button" className="ml-1 underline" onClick={() => void radar.refetch()}>
              Reload status
            </button>
          )}
        </p>
        {s.error && !running && <p className="max-w-md text-[12px] text-bad sm:text-right">{s.error}</p>}
      </div>
      {radar.data && !radar.data.treg && (
        <p className="max-w-md text-[12px] text-muted sm:text-right">
          Without a treg token (TREG_TOKEN) on the server, only the job boards of companies you track are checked.
        </p>
      )}
    </div>
  );
}
