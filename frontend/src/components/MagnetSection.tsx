import { useId, useState } from "react";

import { type MagnetMode, useBuildMagnet, useDeleteMagnet, useMagnets } from "@/api/hooks";
import { MagnetRow } from "@/components/MagnetRow";
import { notify } from "@/components/Toast";
import { Button } from "@/components/ui";
import { competitors as readCompetitors, MODES } from "@/lib/magnets";

/** Build a lead magnet for this company: people in their ICP who engage with their competitors on LinkedIn. */
export function MagnetSection({ companyId, website }: { companyId: string; website: string }) {
  const magnets = useMagnets(companyId);
  const build = useBuildMagnet(companyId);
  const remove = useDeleteMagnet();
  const [site, setSite] = useState(website);
  const [rivals, setRivals] = useState("");
  const [rivalsTouched, setRivalsTouched] = useState(false); // judged once they leave the field, not per keystroke
  const siteId = useId();
  const rivalsId = useId();
  const building = magnets.data?.some((m) => m.status === "running") ?? false;
  const { list: competitors, problem: rivalProblem } = readCompetitors(rivals);
  const rivalsErrorId = useId();

  function start(mode: MagnetMode) {
    build.mutate(
      { mode, website: site.trim() || undefined, competitors },
      {
        onSuccess: () => notify(mode === "full" ? "Building the full list" : "Building the teaser"),
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
            onBlur={() => setRivalsTouched(true)}
            placeholder="rival.com, other.com"
            aria-invalid={rivalProblem && rivalsTouched ? true : undefined}
            aria-describedby={rivalsErrorId}
          />
          <span id={rivalsErrorId} aria-live="polite" className="text-bad">
            {rivalsTouched ? rivalProblem : ""}
          </span>
        </label>
      </div>
      <div className="flex flex-wrap gap-2">
        {MODES.map(({ mode, label, cost }) => (
          <Button
            key={mode}
            variant={mode === "teaser" ? "primary" : "secondary"}
            disabled={building || build.isPending || !site.trim() || Boolean(rivalProblem)}
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
                })
              }
            />
          ))}
        </ul>
      )}
    </div>
  );
}
