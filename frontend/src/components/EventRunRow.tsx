import { ChevronRight } from "lucide-react";
import { Link } from "react-router-dom";

import type { EventRunSummary } from "@/api/hooks";
import { Chip } from "@/components/ui";
import { formatDateTimeDay } from "@/lib/format";
import { statusTone, usd } from "@/lib/events";

export function RunRow({ run }: { run: EventRunSummary }) {
  return (
    <li>
      <Link
        to={`/events/${run.id}`}
        className="flex items-center gap-3 px-4 py-3 hover:bg-chip focus-visible:bg-chip"
        aria-label={`${run.company_name ?? run.domain}: ${run.label}`}
      >
        <div className="min-w-0 flex-1">
          <p className="flex flex-wrap items-center gap-2 text-sm font-medium">
            {run.company_name ?? run.domain}
            {run.company_name && <span className="font-normal text-muted">{run.domain}</span>}
            <Chip tone={statusTone(run.status)}>{run.label}</Chip>
          </p>
          <p className="text-[13px] text-muted">
            Started {formatDateTimeDay(run.created)}
            {run.status === "ready" ? ` · ${run.leads} lead${run.leads === 1 ? "" : "s"}` : ""} · {usd(run.spent_usd)}{" "}
            of {usd(run.budget_usd)}
            {run.detail && run.status !== "ready" ? ` · ${run.detail}` : ""}
          </p>
        </div>
        <ChevronRight size={16} aria-hidden="true" className="text-muted" />
      </Link>
    </li>
  );
}
