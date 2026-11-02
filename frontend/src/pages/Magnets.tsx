import { useId, useState } from "react";

import { type MagnetMode, useAllMagnets, useDeleteMagnet, useStartMagnet } from "@/api/hooks";
import { MagnetRow } from "@/components/MagnetRow";
import { notify } from "@/components/Toast";
import { Button, Card, EmptyState, PageHeader } from "@/components/ui";
import { competitors as readCompetitors, MODES } from "@/lib/magnets";

const field = "min-h-[38px] rounded-lg border border-line bg-surface px-3 text-sm";

/** Start one for any website: a company in the tracker or not. */
function StartForm({ building }: { building: boolean }) {
  const start = useStartMagnet();
  const [name, setName] = useState("");
  const [website, setWebsite] = useState("");
  const [rivals, setRivals] = useState("");
  const [rivalsTouched, setRivalsTouched] = useState(false); // judged once they leave the field, not per keystroke
  const nameId = useId();
  const siteId = useId();
  const rivalsId = useId();
  const rivalsErrorId = useId();
  const { list, problem } = readCompetitors(rivals);

  function build(mode: MagnetMode) {
    start.mutate(
      { mode, website: website.trim(), name: name.trim() || null, competitors: list },
      { onSuccess: () => notify(mode === "full" ? "Building the full list" : "Building the teaser") },
    );
  }

  return (
    <Card className="flex flex-col gap-3 p-4">
      <div className="grid gap-3 sm:grid-cols-3">
        <label htmlFor={siteId} className="flex flex-col gap-1 text-sm">
          <span className="font-medium">Their website</span>
          <input
            id={siteId}
            className={field}
            value={website}
            onChange={(e) => setWebsite(e.target.value)}
            placeholder="acme.com"
          />
        </label>
        <label htmlFor={nameId} className="flex flex-col gap-1 text-sm">
          <span className="font-medium">Company name (optional)</span>
          <input
            id={nameId}
            className={field}
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Acme"
            maxLength={120}
          />
        </label>
        <label htmlFor={rivalsId} className="flex flex-col gap-1 text-sm">
          <span className="font-medium">Competitors you know (optional)</span>
          <input
            id={rivalsId}
            className={field}
            value={rivals}
            onChange={(e) => setRivals(e.target.value)}
            onBlur={() => setRivalsTouched(true)}
            placeholder="rival.com, other.com"
            aria-invalid={problem && rivalsTouched ? true : undefined}
            aria-describedby={rivalsErrorId}
          />
          <span id={rivalsErrorId} aria-live="polite" className="text-bad">
            {rivalsTouched ? problem : ""}
          </span>
        </label>
      </div>
      <div className="flex flex-wrap gap-2">
        {MODES.map(({ mode, label, cost }) => (
          <Button
            key={mode}
            variant={mode === "teaser" ? "primary" : "secondary"}
            disabled={building || start.isPending || !website.trim() || Boolean(problem)}
            onClick={() => build(mode)}
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
        {building && <li>One is already building for a website outside the tracker; start the next when it's done.</li>}
      </ul>
    </Card>
  );
}

export function MagnetsPage() {
  const magnets = useAllMagnets();
  const remove = useDeleteMagnet();
  const unlinkedBuilding = magnets.data?.some((m) => m.status === "running" && m.company_id === null) ?? false;
  return (
    <div className="flex max-w-4xl flex-col gap-6">
      <PageHeader
        eyebrow="People in a company's buyer profile who like or comment on their competitors' LinkedIn posts"
        title="Lead magnets"
      />
      <StartForm building={unlinkedBuilding} />
      {magnets.isPending && <p className="text-sm text-muted">Loading…</p>}
      {magnets.isError && <p className="text-sm text-bad">Couldn't load the lead magnets. {magnets.error.message}</p>}
      {magnets.data &&
        (magnets.data.length ? (
          <ul className="flex flex-col gap-2" aria-label="Lead magnets">
            {magnets.data.map((m) => (
              <MagnetRow
                key={m.id}
                magnet={m}
                heading={m.title}
                deleting={remove.isPending && remove.variables === m.id}
                onDelete={() => remove.mutate(m.id, { onSuccess: () => notify("Deleted") })}
              />
            ))}
          </ul>
        ) : (
          <EmptyState title="No lead magnets yet">
            Build one above for any website, or from a company's panel on Today.
          </EmptyState>
        ))}
    </div>
  );
}
