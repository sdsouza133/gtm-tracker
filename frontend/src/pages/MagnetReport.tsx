import { Download, ExternalLink, Mail } from "lucide-react";
import { useEffect } from "react";
import { useParams } from "react-router-dom";

import { type PublicLead, type PublicMagnet, usePublicMagnet } from "@/api/hooks";
import { Button, Card, Chip, EmptyState } from "@/components/ui";
import { formatDay } from "@/lib/format";
import { SINGLE, TIER, toCsv } from "@/lib/leads";
import { safeUrl } from "@/lib/safe";

function download(report: PublicMagnet) {
  const blob = new Blob([toCsv(report.leads)], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `${report.company || "leads"} - LinkedIn engagers.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

function plural(n: number, one: string, many = `${one}s`) {
  return `${n} ${n === 1 ? one : many}`;
}

function LeadCard({ lead }: { lead: PublicLead }) {
  const tier = TIER[lead.tier] ?? SINGLE;
  const profile = safeUrl(lead.linkedin);
  const role = [lead.title, lead.company].filter(Boolean).join(" at ") || lead.headline;
  return (
    <li className="flex flex-col gap-2 border-b border-line py-4 last:border-b-0">
      <div className="flex flex-wrap items-center gap-2">
        {profile ? (
          <a className="font-semibold text-accent-ink hover:underline" href={profile} target="_blank" rel="noreferrer">
            {lead.name}
            <ExternalLink size={12} className="ml-1 inline" aria-label="(LinkedIn, opens in a new tab)" />
          </a>
        ) : (
          <span className="font-semibold">{lead.name}</span>
        )}
        <Chip tone={tier.tone}>{tier.label}</Chip>
        {lead.country && (
          <span className="text-xs text-muted">{lead.country === "CA" ? "Canada" : "United States"}</span>
        )}
      </div>
      {role && <p className="text-sm">{role}</p>}
      <p className="text-sm text-muted">
        {plural(lead.touches, "touch", "touches")}: {plural(lead.comments, "comment")}, {plural(lead.reactions, "like")}{" "}
        across {plural(lead.posts, "post")} by {lead.competitors.join(" and ") || "competitors"}
        {lead.last ? `, last on ${formatDay(lead.last)}` : ""}.
      </p>
      {lead.said.map((quote) => (
        <blockquote key={quote} className="border-l-2 border-line pl-3 text-sm italic text-body">
          “{quote}”
        </blockquote>
      ))}
      {lead.why_fit && <p className="text-xs text-muted">Why they fit: {lead.why_fit}</p>}
      {lead.email && (
        <a
          className="inline-flex items-center gap-1 text-sm text-accent-ink hover:underline"
          href={`mailto:${lead.email}`}
        >
          <Mail size={14} aria-hidden /> {lead.email}
        </a>
      )}
    </li>
  );
}

function Report({ report }: { report: PublicMagnet }) {
  const rivals = report.competitors.map((c) => c.name).join(", ");
  const teaser = report.mode === "teaser";
  const icp = report.icp;
  return (
    <main className="mx-auto flex max-w-3xl flex-col gap-6 px-4 py-10">
      <header className="flex flex-col gap-2">
        <span className="text-[13px] font-medium text-muted">
          Prepared for {report.company}
          {report.built ? ` on ${formatDay(report.built)}` : ""}
        </span>
        <h1 className="text-[26px] font-bold tracking-tight">
          People in your ICP engaging with {rivals || "your competitors"} on LinkedIn
        </h1>
        <p className="text-body">
          {plural(report.fit, "person", "people")} who fit your ideal customer profile liked or commented on their posts
          in the last month. {report.in_region} of those we looked up are in the US or Canada
          {teaser ? "; here are a few" : ""}.
        </p>
      </header>

      <Card className="flex flex-col gap-2 p-5 text-sm">
        <h2 className="font-semibold">How to read this</h2>
        <p className="text-muted">
          A like is a touchpoint, not intent. What matters is how often someone engages, and how: comments count more
          than likes, and engaging with several posts or several competitors counts more than one.
        </p>
        <ul className="flex flex-col gap-1">
          {Object.values(TIER).map((t) => (
            <li key={t.label} className="flex flex-wrap items-center gap-2">
              <Chip tone={t.tone}>{t.label}</Chip>
              <span className="text-muted">{t.meaning}</span>
            </li>
          ))}
        </ul>
      </Card>

      <Card className="flex flex-col gap-3 p-5">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="font-semibold">The people</h2>
          {report.leads.length > 0 && (
            <Button onClick={() => download(report)}>
              <Download size={14} aria-hidden /> Download CSV
            </Button>
          )}
        </div>
        {report.leads.length ? (
          <ol className="flex flex-col">
            {report.leads.map((lead) => (
              <LeadCard key={`${lead.linkedin}-${lead.name}`} lead={lead} />
            ))}
          </ol>
        ) : (
          <p className="text-sm text-muted">No one in the US or Canada this time.</p>
        )}
        {teaser && (
          <p className="rounded-lg bg-accent-tint p-3 text-sm text-accent-ink">
            {report.more > 0 ? `${plural(report.more, "more person", "more people")} found. ` : ""}
            This is a preview from one competitor. The full list covers up to three competitors and their leaders' own
            posts, with work emails where they can be found.
          </p>
        )}
      </Card>

      <div className="grid gap-4 sm:grid-cols-2">
        <Card className="flex flex-col gap-2 p-5 text-sm">
          <h2 className="font-semibold">Your ICP, as we read it</h2>
          {icp.sells && <p>{icp.sells}</p>}
          {[
            ["Industries", icp.industries],
            ["Company size", icp.company_sizes],
            ["Titles", icp.titles],
            ["Seniority", icp.seniority],
          ].map(([label, values]) =>
            (values as string[]).length ? (
              <p key={label as string} className="text-muted">
                <span className="font-medium text-ink">{label as string}:</span> {(values as string[]).join(", ")}
              </p>
            ) : null,
          )}
        </Card>
        <Card className="flex flex-col gap-2 p-5 text-sm">
          <h2 className="font-semibold">Competitors we read</h2>
          <ul className="flex flex-col gap-2">
            {report.competitors.map((c) => (
              <li key={c.domain}>
                {safeUrl(c.linkedin) ? (
                  <a
                    className="font-medium text-accent-ink hover:underline"
                    href={safeUrl(c.linkedin)}
                    target="_blank"
                    rel="noreferrer"
                  >
                    {c.name}
                  </a>
                ) : (
                  <span className="font-medium">{c.name}</span>
                )}
                {c.why && <span className="text-muted"> · {c.why}</span>}
              </li>
            ))}
          </ul>
        </Card>
      </div>
    </main>
  );
}

/** A lead magnet report, opened from its private link. No sign-in. */
export function MagnetReportPage() {
  const { id = "", token = "" } = useParams();
  const report = usePublicMagnet(id, token);
  useEffect(() => {
    if (report.data) document.title = `${report.data.company}: LinkedIn engagers in your ICP`;
  }, [report.data]);
  if (report.isPending) return <p className="p-8 text-sm text-muted">Loading…</p>;
  if (report.isError)
    return (
      <div className="mx-auto mt-24 max-w-sm px-4">
        <EmptyState title="This report isn't available">
          <p>{report.error.message}</p>
        </EmptyState>
      </div>
    );
  return <Report report={report.data} />;
}
