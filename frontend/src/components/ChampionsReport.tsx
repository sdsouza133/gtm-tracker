import { Download, ExternalLink } from "lucide-react";

import type { Champion, ChampionsReport } from "@/api/hooks";
import { IcpCard } from "@/components/IcpCard";
import { Button, Card, Chip } from "@/components/ui";
import { championsCsv, GRADE, period, REASON, roleLine, since } from "@/lib/champions";
import { formatDay } from "@/lib/format";
import { safeUrl } from "@/lib/safe";

function plural(n: number, one: string, many = `${one}s`) {
  return `${n} ${n === 1 ? one : many}`;
}

function download(report: ChampionsReport) {
  const blob = new Blob([championsCsv(report)], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `${report.company || "champions"} - champions who moved.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

function Name({ name, linkedin }: { name: string; linkedin: string }) {
  const profile = safeUrl(linkedin);
  return profile ? (
    <a className="font-semibold text-accent-ink hover:underline" href={profile} target="_blank" rel="noreferrer">
      {name}
      <ExternalLink size={12} className="ml-1 inline" aria-label="(LinkedIn, opens in a new tab)" />
    </a>
  ) : (
    <span className="font-semibold">{name}</span>
  );
}

/** One champion. `fresh` marks those the last report for this company didn't have. */
function ChampionCard({ c, fresh }: { c: Champion; fresh: boolean }) {
  const grade = GRADE[c.grade];
  const when = period(c.was);
  return (
    <li className="flex flex-col gap-1.5 border-b border-line py-4 last:border-b-0">
      <div className="flex flex-wrap items-center gap-2">
        <Name name={c.name} linkedin={c.linkedin} />
        <Chip tone={grade.tone}>{grade.label}</Chip>
        {fresh && c.new && <Chip tone="warm">New since the last report</Chip>}
      </div>
      <p className="text-sm">
        <span className="text-muted">Was: </span>
        {roleLine(c.was)}
        {when ? ` (${when})` : ""}
      </p>
      <p className="text-sm">
        <span className="text-muted">Now: </span>
        {roleLine(c.now)}
        {c.now.industry ? ` · ${c.now.industry}` : ""} · {since(c.now.months)}
      </p>
      {c.why && <p className="text-xs text-muted">Why they matter: {c.why}</p>}
    </li>
  );
}

/** A champion report: the people who used the company's product at a customer and just moved to a company in its
 * ICP. The shared link shows the top few; the owner (`owner`) also sees everyone, the watch list and who was left
 * out, and can download the CSV. */
export function ChampionsReportView({ report, owner }: { report: ChampionsReport; owner: boolean }) {
  const matched = report.customers.filter((c) => c.linkedin);
  const skipped = Object.entries(report.skipped).sort((a, b) => b[1] - a[1]);
  return (
    <article className="flex flex-col gap-6">
      <header className="flex flex-col gap-2">
        <span className="text-[13px] font-medium text-muted">
          Prepared for {report.company}
          {report.built ? ` on ${formatDay(report.built)}` : ""}
        </span>
        <h1 className="text-[26px] font-bold tracking-tight">Your champions who just moved to new companies</h1>
        <p className="text-body">
          {plural(report.movers, "person", "people")} left your customers in the last 90 days. Below are the ones who
          just started at a company that fits your ICP. Each worked at one of your customers, and the grade says how
          sure it is that they used your product there.
        </p>
      </header>

      <Card className="flex flex-col gap-2 p-5 text-sm">
        <h2 className="font-semibold">How to read this</h2>
        <ul className="flex flex-col gap-1">
          {Object.values(GRADE).map((g) => (
            <li key={g.label} className="flex flex-wrap items-center gap-2">
              <Chip tone={g.tone}>{g.label}</Chip>
              <span className="text-muted">{g.meaning}</span>
            </li>
          ))}
        </ul>
      </Card>

      <Card className="flex flex-col gap-3 p-5">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="font-semibold">The champions</h2>
          {owner && report.champions.length > 0 && (
            <Button onClick={() => download(report)}>
              <Download size={14} aria-hidden /> Download CSV
            </Button>
          )}
        </div>
        {report.champions.length ? (
          <ol className="flex flex-col">
            {report.champions.map((c) => (
              <ChampionCard key={`${c.linkedin}-${c.name}`} c={c} fresh={owner && report.repeat} />
            ))}
          </ol>
        ) : (
          <p className="text-sm text-muted">No one has moved to a company in your ICP in the last 90 days.</p>
        )}
        {report.more > 0 && (
          <p className="rounded-lg bg-accent-tint p-3 text-sm text-accent-ink">
            {plural(report.more, "more champion")} found. Reply to get the full list, and a fresh one each month.
          </p>
        )}
      </Card>

      <div className="grid gap-4 sm:grid-cols-2">
        <IcpCard icp={report.icp} />
        <Card className="flex flex-col gap-2 p-5 text-sm">
          <h2 className="font-semibold">Customers we tracked</h2>
          <p className="text-muted">
            {plural(report.customers.length, "customer")} named on your website, {matched.length} found on LinkedIn.
          </p>
          <ul className="flex flex-wrap gap-1.5">
            {report.customers.map((c) => (
              <li key={c.name}>
                <Chip tone={c.linkedin ? "neutral" : "warm"}>
                  {c.name}
                  {owner && c.linkedin && c.linkedin_name && c.linkedin_name !== c.name ? ` → ${c.linkedin_name}` : ""}
                  {c.linkedin ? "" : " · no LinkedIn page found"}
                </Chip>
              </li>
            ))}
          </ul>
        </Card>
      </div>

      {owner && (
        <>
          <Card className="flex flex-col gap-2 p-5 text-sm">
            <h2 className="font-semibold">Watch list</h2>
            <p className="text-muted">
              People the website names who haven't moved yet. Build the report again next month to catch them when they
              do.
            </p>
            {report.watch.length ? (
              <ul className="flex flex-col gap-1">
                {report.watch.map((w) => (
                  <li key={`${w.name}-${w.company}`} className="flex flex-wrap items-center gap-2">
                    <Name name={w.name} linkedin={w.linkedin} />
                    <span className="text-muted">
                      {[w.title, w.company].filter(Boolean).join(" at ")}
                      {w.status === "still_there" && " · still there"}
                      {w.status === "moved" && ` · moved a while ago${w.now ? `, now ${w.now}` : ""}`}
                      {w.status === "unchecked" && " · no LinkedIn address on the site to check"}
                      {w.status === "not_found" && " · their profile couldn't be read"}
                    </span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-muted">Nobody else is named on the website.</p>
            )}
          </Card>
          <Card className="flex flex-col gap-2 p-5 text-sm">
            <h2 className="font-semibold">Left out, and why</h2>
            {skipped.length ? (
              <ul className="flex flex-col gap-1">
                {skipped.map(([reason, count]) => (
                  <li key={reason}>
                    <span className="font-medium">{count}</span>{" "}
                    <span className="text-muted">{REASON[reason] ?? reason}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-muted">Nobody was left out.</p>
            )}
            {report.skipped_people.length > 0 && (
              <details>
                <summary className="cursor-pointer text-accent-ink">Who</summary>
                <ul className="mt-2 flex flex-col gap-1">
                  {report.skipped_people.map((p) => (
                    <li key={`${p.linkedin}-${p.reason}`} className="text-muted">
                      <Name name={p.name} linkedin={p.linkedin} />
                      {p.now ? `, ${p.now}` : ""}: {REASON[p.reason] ?? p.reason}
                    </li>
                  ))}
                </ul>
              </details>
            )}
            <p className="text-xs text-muted">LinkedIn data for this report: ${report.linkedin_usd.toFixed(2)}.</p>
          </Card>
        </>
      )}
    </article>
  );
}
