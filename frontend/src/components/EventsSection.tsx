import { useNavigate } from "react-router-dom";

import { useEventsHome, useStartEventRun } from "@/api/hooks";
import { Button } from "@/components/ui";
import { RunRow } from "@/components/EventRunRow";
import { blocked } from "@/lib/events";

/** The events tool for one company: start a run from its website, and its runs so far. */
export function EventsSection({ companyId, website }: { companyId: string; website: string }) {
  const home = useEventsHome(companyId);
  const start = useStartEventRun();
  const navigate = useNavigate();
  const reason = home.data ? blocked(home.data) : "";
  const site = website.trim();

  return (
    <div className="flex flex-col gap-3">
      <p className="text-sm text-muted">
        People who post that they're going to (or just went to) the events their buyers attend, kept when they fit the
        ICP, with verified work emails. You approve the plan before anything is searched.
      </p>
      <div>
        <Button
          variant="secondary"
          disabled={!site || Boolean(reason) || start.isPending || home.isPending}
          onClick={() =>
            start.mutate(
              { website: site, company_id: companyId },
              { onSuccess: (run) => navigate(`/events/${run.id}`) },
            )
          }
        >
          Find their buyers at events
        </Button>
        {(reason || !site) && (
          <p className="mt-1 text-[13px] text-muted">{reason || "Add the company's website to start a run."}</p>
        )}
      </div>
      {home.isError && <p className="text-sm text-bad">Couldn't load the events runs. {home.error.message}</p>}
      {home.data && home.data.runs.length > 0 && (
        <ul className="divide-y divide-line rounded-lg border border-line" aria-label="Events runs">
          {home.data.runs.map((run) => (
            <RunRow key={run.id} run={run} />
          ))}
        </ul>
      )}
    </div>
  );
}
