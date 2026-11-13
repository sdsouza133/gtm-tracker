import { Copy, ExternalLink, Trash2 } from "lucide-react";

import type { Magnet } from "@/api/hooks";
import { notify } from "@/components/Toast";
import { Button, Chip } from "@/components/ui";

function when(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? ""
    : d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

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

/** One lead magnet: its progress or result, its private link, and delete. `heading` replaces the "Teaser, Nov 2"
 * name, for a list of every company's magnets. */
export function MagnetRow({
  magnet,
  onDelete,
  deleting,
  heading,
}: {
  magnet: Magnet;
  onDelete: () => void;
  deleting: boolean;
  heading?: string;
}) {
  const s = magnet.summary;
  const link = magnet.link;
  const name =
    heading ??
    `${magnet.mode === "full" ? "Full list" : "Teaser"}${when(magnet.created) ? `, ${when(magnet.created)}` : ""}`;
  return (
    <li className="flex flex-col gap-2 rounded-lg border border-line p-3 text-sm">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="font-medium">{name}</span>
        {/* progress and the end of a build are announced to screen readers as they happen */}
        <span aria-live="polite">
          {magnet.status === "running" && <Chip tone="accent">Building: {magnet.step || "starting"}</Chip>}
          {magnet.status === "ready" && <Chip tone="good">Ready</Chip>}
          {magnet.status === "failed" && <Chip tone="bad">Didn't finish</Chip>}
        </span>
      </div>
      {magnet.status === "failed" && magnet.error && <p className="text-bad">{magnet.error}</p>}
      {s && (
        <p className="text-muted">
          {s.leads} in the US or Canada ({s.hot} hot, {s.warm} warm, {s.touch} single touch) out of {s.fit} who fit the
          ICP{magnet.mode === "full" ? `, ${s.emails} with emails` : ""}. LinkedIn data ${s.linkedin_usd.toFixed(2)}.
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
          aria-label={`Delete ${name}${link ? " and turn its link off" : ""}`}
        >
          <Trash2 size={14} aria-hidden /> Delete
        </Button>
      </div>
    </li>
  );
}
