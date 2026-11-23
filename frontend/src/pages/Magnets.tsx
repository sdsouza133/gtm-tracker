import { clsx } from "clsx";
import { useId, useState } from "react";

import { type MagnetKind, type MagnetMode, useAllMagnets, useDeleteMagnet, useStartMagnet } from "@/api/hooks";
import { MagnetRow } from "@/components/MagnetRow";
import { notify } from "@/components/Toast";
import { Button, Card, EmptyState, PageHeader } from "@/components/ui";
import { CHAMPIONS_COST, competitors as readCompetitors, MODES } from "@/lib/magnets";

const field = "min-h-[38px] rounded-lg border border-line bg-surface px-3 text-sm";

const KINDS: { kind: MagnetKind; label: string; about: string }[] = [
  {
    kind: "engagement",
    label: "Engagers",
    about: "People in their ICP who like or comment on their competitors' LinkedIn posts.",
  },
  {
    kind: "champions",
    label: "Champions who moved",
    about: "People who used their product at one of their customers and just started at a company in their ICP.",
  },
];

/** Start one for any website: a company in the tracker or not. `busy` says which kinds are building already. */
function StartForm({ busy }: { busy: Record<MagnetKind, boolean> }) {
  const start = useStartMagnet();
  const [kind, setKind] = useState<MagnetKind>("engagement");
  const [name, setName] = useState("");
  const [website, setWebsite] = useState("");
  const [rivals, setRivals] = useState("");
  const [rivalsTouched, setRivalsTouched] = useState(false); // judged once they leave the field, not per keystroke
  const nameId = useId();
  const siteId = useId();
  const rivalsId = useId();
  const rivalsErrorId = useId();
  const champions = kind === "champions";
  const { list, problem: rivalsProblem } = readCompetitors(rivals);
  const problem = champions ? "" : rivalsProblem;
  const disabled = busy[kind] || start.isPending || !website.trim() || Boolean(problem);

  function build(mode: MagnetMode) {
    start.mutate(
      champions
        ? { kind, website: website.trim(), name: name.trim() || null }
        : { kind, mode, website: website.trim(), name: name.trim() || null, competitors: list },
      {
        onSuccess: () =>
          notify(
            champions
              ? "Building the champion report"
              : mode === "full"
                ? "Building the full list"
                : "Building the teaser",
          ),
      },
    );
  }

  return (
    <Card className="flex flex-col gap-3 p-4">
      <fieldset className="flex flex-col gap-2">
        <legend className="mb-1 text-sm font-medium">What to build</legend>
        <div className="flex flex-wrap gap-1">
          {KINDS.map((k) => (
            <label
              key={k.kind}
              className={clsx(
                "flex min-h-[34px] cursor-pointer items-center gap-2 rounded-lg px-3 text-sm font-medium has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-accent",
                kind === k.kind ? "bg-accent-tint text-accent-ink" : "text-muted hover:bg-chip",
              )}
            >
              <input
                type="radio"
                name="magnet-kind"
                className="sr-only"
                value={k.kind}
                checked={kind === k.kind}
                onChange={() => setKind(k.kind)}
              />
              {k.label}
            </label>
          ))}
        </div>
        <p className="text-sm text-muted">{KINDS.find((k) => k.kind === kind)?.about}</p>
      </fieldset>
      <div className={clsx("grid gap-3", champions ? "sm:grid-cols-2" : "sm:grid-cols-3")}>
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
        {!champions && (
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
        )}
      </div>
      {champions ? (
        <>
          <div>
            <Button variant="primary" disabled={disabled} onClick={() => build("teaser")} title={CHAMPIONS_COST}>
              Build the champion report
            </Button>
          </div>
          <ul className="text-xs text-muted">
            <li>Finds {CHAMPIONS_COST}.</li>
            {busy.champions && <li>A champion report is building; start the next when it's done.</li>}
          </ul>
        </>
      ) : (
        <>
          <div className="flex flex-wrap gap-2">
            {MODES.map(({ mode, label, cost }) => (
              <Button
                key={mode}
                variant={mode === "teaser" ? "primary" : "secondary"}
                disabled={disabled}
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
            {busy.engagement && (
              <li>One is already building for a website outside the tracker; start the next when it's done.</li>
            )}
          </ul>
        </>
      )}
      {start.isError && <p className="text-sm text-bad">{start.error.message}</p>}
    </Card>
  );
}

export function MagnetsPage() {
  const magnets = useAllMagnets();
  const remove = useDeleteMagnet();
  const running = magnets.data?.filter((m) => m.status === "running") ?? [];
  const busy: Record<MagnetKind, boolean> = {
    // one engagement build at a time for websites outside the tracker; one champion report at a time anywhere
    engagement: running.some((m) => m.kind !== "champions" && m.company_id === null),
    champions: running.some((m) => m.kind === "champions"),
  };
  return (
    <div className="flex max-w-4xl flex-col gap-6">
      <PageHeader
        eyebrow="Free lists for a company: people in their ICP engaging with their competitors, or their champions who just moved"
        title="Lead magnets"
      />
      <StartForm busy={busy} />
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
            Build one above for any website, from a company's panel on Today, or from a Fractional card.
          </EmptyState>
        ))}
    </div>
  );
}
