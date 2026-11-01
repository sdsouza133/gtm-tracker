import { Copy, ExternalLink, Trash2 } from "lucide-react";
import { useId, useState } from "react";

import { type Magnet, type MagnetMode, useBuildMagnet, useDeleteMagnet, useMagnets } from "@/api/hooks";
import { notify } from "@/components/Toast";
import { Button, Chip } from "@/components/ui";

const MODES: { mode: MagnetMode; label: string; cost: string }[] = [
  { mode: "teaser", label: "Build a teaser", cost: "1 competitor, a few examples, about $0.40" },
  { mode: "full", label: "Build the full list", cost: "up to 3 competitors, work emails where found, up to about $2" },
];

function absolute(link: string): string {
  return new URL(link, window.location.origin).toString();
}

async function copyLink(link: string) {
  try {
    await navigator.clipboard.writeText(absolute(link));
    notify("Link copied");
  } catch {
    notify("Couldn't copy. Open the report and copy its address instead.", "error");
  }
}

function MagnetRow({ magnet, onDelete, deleting }: { magnet: Magnet; onDelete: () => void; deleting: boolean }) {
  const s = magnet.summary;
  const link = magnet.link;
  return (
    <li className="flex flex-col gap-2 rounded-lg border border-line p-3 text-sm">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="font-medium">{magnet.mode === "full" ? "Full list" : "Teaser"}</span>
        {magnet.status === "running" && <Chip tone="accent">Building: {magnet.step || "starting"}</Chip>}
        {magnet.status === "ready" && <Chip tone="good">Ready</Chip>}
        {magnet.status === "failed" && <Chip tone="bad">Didn't finish</Chip>}
      </div>
      {magnet.status === "failed" && magnet.error && <p className="text-bad">{magnet.error}</p>}
      {s && (
        <p className="text-muted">
          {s.leads} in the US or Canada ({s.hot} hot, {s.warm} warm, {s.touch} single touch) out of {s.fit} who fit the
          ICP{magnet.mode === "full" ? `, ${s.emails} with emails` : ""}. Apify ${s.apify_usd.toFixed(2)}.
          {magnet.views ? ` Opened ${magnet.views} time${magnet.views === 1 ? "" : "s"}.` : ""}
        </p>
      )}
      <div className="flex flex-wrap gap-2">
        {link && (
          <>
            <Button onClick={() => void copyLink(link)}>
              <Copy size={14} aria-hidden /> Copy link
            </Button>
            <a
              className="inline-flex min-h-[38px] items-center gap-2 rounded-lg px-3 text-sm font-medium text-accent-ink hover:bg-chip"
              href={link}
              target="_blank"
              rel="noreferrer"
            >
              <ExternalLink size={14} aria-hidden /> Open report
            </a>
          </>
        )}
        <Button
          variant="quiet"
          onClick={onDelete}
          disabled={deleting}
          aria-label={`Delete this ${magnet.mode === "full" ? "full list" : "teaser"}${link ? " and turn its link off" : ""}`}
        >
          <Trash2 size={14} aria-hidden /> Delete
        </Button>
      </div>
    </li>
  );
}

/** Build a lead magnet for this company: people in their ICP who engage with their competitors on LinkedIn. */
export function MagnetSection({ companyId, website }: { companyId: string; website: string }) {
  const magnets = useMagnets(companyId);
  const build = useBuildMagnet(companyId);
  const remove = useDeleteMagnet(companyId);
  const [site, setSite] = useState(website);
  const [rivals, setRivals] = useState("");
  const siteId = useId();
  const rivalsId = useId();
  const building = magnets.data?.some((m) => m.status === "running") ?? false;

  function start(mode: MagnetMode) {
    const competitors = rivals
      .split(/[\s,]+/)
      .map((r) => r.trim())
      .filter(Boolean)
      .slice(0, 5);
    build.mutate(
      { mode, website: site.trim() || undefined, competitors },
      {
        onSuccess: () => notify(mode === "full" ? "Building the full list" : "Building the teaser"),
        onError: (e) => notify(e.message, "error"),
      },
    );
  }

  return (
    <div className="flex flex-col gap-3">
      <p className="text-sm text-muted">
        People in their ICP who like or comment on their competitors' LinkedIn posts, ranked by how often they engage.
        US and Canada only.
      </p>
      <div className="grid gap-2 sm:grid-cols-2">
        <label htmlFor={siteId} className="flex flex-col gap-1 text-sm">
          <span className="font-medium">Their website</span>
          <input
            id={siteId}
            className="rounded-lg border border-line px-3 py-2"
            value={site}
            onChange={(e) => setSite(e.target.value)}
            placeholder="acme.com"
          />
        </label>
        <label htmlFor={rivalsId} className="flex flex-col gap-1 text-sm">
          <span className="font-medium">Competitors you know (optional)</span>
          <input
            id={rivalsId}
            className="rounded-lg border border-line px-3 py-2"
            value={rivals}
            onChange={(e) => setRivals(e.target.value)}
            placeholder="rival.com, other.com"
          />
        </label>
      </div>
      <div className="flex flex-wrap gap-2">
        {MODES.map(({ mode, label, cost }) => (
          <Button
            key={mode}
            variant={mode === "teaser" ? "primary" : "secondary"}
            disabled={building || build.isPending || !site.trim()}
            onClick={() => start(mode)}
            title={cost}
          >
            {label}
          </Button>
        ))}
      </div>
      <ul className="text-xs text-muted">
        {MODES.map(({ mode, label, cost }) => (
          <li key={mode}>
            {label}: {cost}.
          </li>
        ))}
      </ul>
      {magnets.isPending && <p className="text-sm text-muted">Loading…</p>}
      {magnets.isError && <p className="text-sm text-bad">Couldn't load the lead magnets. {magnets.error.message}</p>}
      {magnets.data && magnets.data.length > 0 && (
        <ul className="flex flex-col gap-2" aria-label="Lead magnets">
          {magnets.data.map((m) => (
            <MagnetRow
              key={m.id}
              magnet={m}
              deleting={remove.isPending && remove.variables === m.id}
              onDelete={() =>
                remove.mutate(m.id, {
                  onSuccess: () => notify("Deleted"),
                  onError: (e) => notify(e.message, "error"),
                })
              }
            />
          ))}
        </ul>
      )}
    </div>
  );
}
