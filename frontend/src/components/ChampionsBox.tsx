import { Copy, FileText, RefreshCw, Users } from "lucide-react";
import { Link } from "react-router-dom";

import { useChampionReports, useStartMagnet } from "@/api/hooks";
import { copyLink } from "@/components/MagnetRow";
import { Button, Chip } from "@/components/ui";
import { championsDetail, championsLine } from "@/lib/champions";
import { CHAMPIONS_COST, domainOf } from "@/lib/magnets";

const linkButton =
  "inline-flex min-h-[38px] items-center gap-2 rounded-lg px-3 text-sm font-medium text-accent-ink hover:bg-chip";

/** A company's champion report, from its card: build one, follow it, then open it, copy its link to send, or build it
 * again to see who's new. The latest report for the company's website is the one shown. */
export function ChampionsBox({ name, website }: { name: string; website: string | null }) {
  const domain = domainOf(website ?? "");
  const reports = useChampionReports(domain);
  const start = useStartMagnet();
  const latest = reports.data?.[0];
  const building = latest?.status === "running";

  if (!domain) return null; // nothing to read customers from

  function build() {
    start.mutate({ kind: "champions", website: website ?? domain, name });
  }

  const startButton = (label: string, icon = <Users size={14} aria-hidden />) => (
    <Button onClick={build} disabled={building || start.isPending} title={`Champion report: ${CHAMPIONS_COST}`}>
      {icon} {label}
    </Button>
  );

  return (
    <section aria-label="Champion report" className="flex flex-col gap-2 rounded-lg border border-line p-3 text-sm">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="font-semibold">Champion report</span>
        <span aria-live="polite">
          {(building || start.isPending) && <Chip tone="accent">Building: {latest?.step || "starting"}</Chip>}
          {!building && !start.isPending && latest?.status === "failed" && <Chip tone="bad">Didn't finish</Chip>}
        </span>
      </div>
      {reports.isError && <p className="text-bad">Couldn't load the champion reports. {reports.error.message}</p>}
      {start.isError && <p className="text-bad">{start.error.message}</p>}
      {reports.data && !latest && (
        <>
          <p className="text-muted">
            People who used {name}'s product at one of its customers and just moved to a company in its ICP: an easy
            sell, and a list to send them for free.
          </p>
          <div>{startButton("Build the champion report")}</div>
          <p className="text-xs text-muted">Finds {CHAMPIONS_COST}.</p>
        </>
      )}
      {latest?.status === "failed" && !building && (
        <>
          {latest.error && <p className="text-bad">{latest.error}</p>}
          <div>{startButton("Try again", <RefreshCw size={14} aria-hidden />)}</div>
        </>
      )}
      {latest?.status === "ready" && latest.champions && (
        <>
          <p className="font-medium">{championsLine(latest.champions)}</p>
          <p className="text-muted">{championsDetail(latest.champions)}.</p>
          <div className="flex flex-wrap gap-2">
            <Link className={linkButton} to={`/magnets/${latest.id}`}>
              <FileText size={14} aria-hidden /> Open report
            </Link>
            {latest.link && (
              <Button onClick={() => void copyLink(latest.link ?? "")}>
                <Copy size={14} aria-hidden /> Copy link
              </Button>
            )}
            {startButton("Build again", <RefreshCw size={14} aria-hidden />)}
          </div>
        </>
      )}
    </section>
  );
}
