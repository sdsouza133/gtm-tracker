import { ArrowLeft, Copy, ExternalLink } from "lucide-react";
import { Link, useParams } from "react-router-dom";

import { useMagnet, useMagnetReport } from "@/api/hooks";
import { ChampionsReportView } from "@/components/ChampionsReport";
import { copyLink } from "@/components/MagnetRow";
import { Button, EmptyState } from "@/components/ui";
import { EngagementReport } from "@/pages/MagnetReport";

const linkButton =
  "inline-flex min-h-[38px] items-center gap-2 rounded-lg px-3 text-sm font-medium text-accent-ink hover:bg-chip";

/** A finished report in full, for the owner: everything the shared link shows and what it leaves out. */
export function MagnetPage() {
  const { id = "" } = useParams();
  const magnet = useMagnet(id);
  const report = useMagnetReport(id);
  const link = magnet.data?.link;
  return (
    <div className="flex max-w-3xl flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Link className={linkButton} to="/magnets">
          <ArrowLeft size={14} aria-hidden /> Lead magnets
        </Link>
        {link && (
          <div className="flex flex-wrap gap-2">
            <Button onClick={() => void copyLink(link)}>
              <Copy size={14} aria-hidden /> Copy link to send
            </Button>
            <a className={linkButton} href={link} target="_blank" rel="noreferrer">
              <ExternalLink size={14} aria-hidden /> What they'll see
            </a>
          </div>
        )}
      </div>
      {report.isPending && <p className="text-sm text-muted">Loading…</p>}
      {report.isError && (
        <EmptyState title="This report isn't available">
          <p>{report.error.message}</p>
        </EmptyState>
      )}
      {report.data &&
        (report.data.kind === "champions" ? (
          <ChampionsReportView report={report.data} owner />
        ) : (
          <EngagementReport report={report.data} full />
        ))}
    </div>
  );
}
