import { Check, Copy, ExternalLink, Linkedin, Mail, Video, X } from "lucide-react";
import { useEffect, useRef, type ReactNode } from "react";
import { Link } from "react-router-dom";

import {
  type Move,
  type Person,
  type Step,
  lookupFailed,
  useCompany,
  useEnrichCompany,
  useReply,
  useTickStep,
  useUpdateMove,
  useUpdatePerson,
} from "@/api/hooks";
import { COPY_FOR, copy, findDraft } from "@/components/MoveRow";
import { trapTab } from "@/components/ProspectDrawer";
import { Button, Chip } from "@/components/ui";
import { ROLE_LABEL, SURE_LABEL, formatDay, stageLabel } from "@/lib/format";
import { safeUrl, strings } from "@/lib/safe";

/** A first touch is done on a day, marked not possible ("na"), or still to do. */
function stepDay(move: Move | undefined, step: "email" | "request"): string | undefined {
  const day = move?.sequence?.steps?.[step];
  return typeof day === "string" ? day : undefined;
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-2">
      <h3 className="text-[13px] font-semibold uppercase tracking-wide text-muted">{title}</h3>
      {children}
    </section>
  );
}

/** One way of reaching someone (email or LinkedIn): what to copy or open, and the tick for "sent". */
function Channel({
  icon,
  label,
  done,
  busy,
  onDone,
  children,
}: {
  icon: ReactNode;
  label: string;
  done: string | undefined;
  busy: boolean;
  onDone: () => void;
  children: ReactNode;
}) {
  const sent = done && done !== "na";
  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="flex w-24 items-center gap-1.5 text-[13px] font-medium text-muted">
        {icon}
        {label}
      </span>
      <div className="flex min-w-0 flex-1 flex-wrap items-center gap-1">{children}</div>
      {sent ? (
        <Chip tone="good">
          <Check size={12} aria-hidden="true" /> Sent {formatDay(done)}
        </Chip>
      ) : done === "na" ? (
        <Chip>Not possible</Chip>
      ) : (
        <Button variant="secondary" disabled={busy} onClick={onDone}>
          <Check size={14} aria-hidden="true" />
          Sent
        </Button>
      )}
    </div>
  );
}

const linkClass =
  "inline-flex min-h-[34px] items-center gap-1.5 rounded-lg px-2.5 text-sm font-medium text-muted hover:bg-chip hover:text-ink";

type Lookup = { looking: boolean; failed: boolean; retry: () => void };

function PersonCard({ person, move, lookup }: { person: Person; move: Move | undefined; lookup: Lookup }) {
  const tick = useTickStep();
  const update = useUpdateMove();
  const reply = useReply();
  const patch = useUpdatePerson();
  const busy = tick.isPending || update.isPending || reply.isPending || patch.isPending;
  const open = move?.status === "open";
  const sent = (s: "email" | "request") => (move ? () => tick.mutate({ id: move.id, step: s as Step }) : () => {});
  const emailDraft = findDraft(person, COPY_FOR.email?.draft ?? []);
  const noteDraft = findDraft(person, COPY_FOR.request?.draft ?? []);
  const linkedin = safeUrl(person.linkedin);
  const loom = person.details["loom"];

  return (
    <article className="flex flex-col gap-3 rounded-card border border-line p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="font-semibold">{person.name}</p>
          <p className="text-[13px] text-muted">{person.title}</p>
        </div>
        <div className="flex flex-wrap gap-1.5">
          <Chip tone="accent">{ROLE_LABEL[person.role_in_hire]}</Chip>
          {person.sureness && <Chip>{SURE_LABEL[person.sureness]}</Chip>}
          {person.status === "replied" && <Chip tone="good">Replied</Chip>}
          {loom === "asked" && <Chip tone="warm">Wants a Loom</Chip>}
        </div>
      </div>

      {move && open && (
        <>
          <Channel
            icon={<Mail size={14} aria-hidden="true" />}
            label="Email"
            done={stepDay(move, "email")}
            busy={busy}
            onDone={sent("email")}
          >
            {person.email ? (
              <a className={linkClass} href={`mailto:${person.email}`}>
                {person.email}
              </a>
            ) : (
              <>
                <span aria-live="polite" className={`px-2.5 text-sm ${lookup.failed ? "text-bad" : "text-muted"}`}>
                  {lookup.looking
                    ? "Looking up the email…"
                    : person.details["apollo_tried"]
                      ? "No email found"
                      : lookup.failed
                        ? "Couldn't look up the email"
                        : "No email yet"}
                </span>
                {lookup.failed && !person.details["apollo_tried"] && (
                  <Button variant="quiet" disabled={lookup.looking} onClick={lookup.retry}>
                    Try again
                  </Button>
                )}
              </>
            )}
            {emailDraft && (
              <Button variant="quiet" onClick={() => void copy(emailDraft, "Email")}>
                <Copy size={14} aria-hidden="true" />
                Copy email
              </Button>
            )}
          </Channel>
          <Channel
            icon={<Linkedin size={14} aria-hidden="true" />}
            label="LinkedIn"
            done={stepDay(move, "request")}
            busy={busy}
            onDone={sent("request")}
          >
            {linkedin && (
              <a className={linkClass} href={linkedin} target="_blank" rel="noreferrer">
                Open profile <ExternalLink size={12} aria-hidden="true" />
              </a>
            )}
            {noteDraft && (
              <Button variant="quiet" onClick={() => void copy(noteDraft, "Note")}>
                <Copy size={14} aria-hidden="true" />
                Copy note
              </Button>
            )}
          </Channel>
        </>
      )}

      <div className="flex flex-wrap gap-1 border-t border-line-soft pt-2">
        {person.status !== "replied" && (
          <Button variant="quiet" disabled={busy} onClick={() => reply.mutate({ id: person.id, text: "" })}>
            They replied
          </Button>
        )}
        {loom !== "asked" && loom !== "sent" && (
          <Button variant="quiet" disabled={busy} onClick={() => patch.mutate({ id: person.id, loom: "asked" })}>
            <Video size={14} aria-hidden="true" />
            Asked for a Loom
          </Button>
        )}
        {move && open && (
          <Button
            variant="quiet"
            disabled={busy}
            onClick={() => update.mutate({ id: move.id, status: "skipped", skip_reason: "Skipped" })}
          >
            Skip
          </Button>
        )}
      </div>
    </article>
  );
}

/** Everything about one company in a side panel: what they do, how they score, the role, and each person to reach by
 * email and LinkedIn. */
export function CompanyPanel({ id, onClose }: { id: string; onClose: () => void }) {
  const { data: c, isPending, isError } = useCompany(id);
  const update = useUpdateMove();
  const enrich = useEnrichCompany();
  const missing = c?.people.some((p) => !p.left && !p.email && !p.details["apollo_tried"]) ?? false;
  const asked = useRef(false);
  useEffect(() => {
    if (missing && !asked.current) {
      asked.current = true; // once per opening; each person is only looked up once anyway
      enrich.mutate(id);
    }
  }, [missing, id, enrich]);
  const lookup = { looking: enrich.isPending, failed: lookupFailed(enrich.error), retry: () => enrich.mutate(id) };
  const panel = useRef<HTMLDivElement>(null);
  const close = useRef(onClose);
  useEffect(() => {
    close.current = onClose;
  });
  useEffect(() => {
    const before = document.activeElement as HTMLElement | null;
    panel.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") close.current();
      if (e.key === "Tab" && panel.current) trapTab(e, panel.current);
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      before?.focus();
    };
  }, []);

  const research = c?.research ?? {};
  const text = (key: string) => (typeof research[key] === "string" ? (research[key] as string) : "");
  const signals = Array.isArray(research["signals"]) ? strings(research["signals"]).slice(0, 2).join(" ") : "";
  const about = text("pmf_reason") || text("apollo_about") || text("industry") || signals;
  const reachFor = (personId: string) =>
    c?.moves.find((m) => m.person_id === personId && m.type === "reach" && m.status === "open") ??
    c?.moves.find((m) => m.person_id === personId && m.type === "reach");
  const apply = c?.moves.find((m) => m.type === "apply" && m.status === "open");
  const people = [...(c?.people ?? [])]
    .filter((p) => !p.left)
    .sort((a, b) => Number(reachFor(b.id)?.status === "open") - Number(reachFor(a.id)?.status === "open"));

  return (
    <div className="fixed inset-0 z-40 flex justify-end">
      <button type="button" aria-label="Close" tabIndex={-1} className="absolute inset-0 bg-ink/30" onClick={onClose} />
      <div
        ref={panel}
        role="dialog"
        aria-modal="true"
        aria-label={c?.name ?? "Company"}
        tabIndex={-1}
        className="relative flex h-full w-full max-w-2xl flex-col overflow-y-auto bg-surface shadow-2xl outline-none"
      >
        {isPending ? (
          <p className="p-6 text-sm text-muted">Loading…</p>
        ) : isError || !c ? (
          <p className="p-6 text-sm text-bad">Couldn't load this company.</p>
        ) : (
          <>
            <header className="flex flex-col gap-2 border-b border-line p-5">
              <div className="flex items-start justify-between gap-3">
                <h2 className="text-xl font-bold">{c.name}</h2>
                <button type="button" aria-label="Close" onClick={onClose} className="rounded p-1 hover:bg-chip">
                  <X size={18} aria-hidden="true" />
                </button>
              </div>
              <div className="flex flex-wrap gap-1.5">
                {c.score ? <Chip tone="accent">Score {c.score.toFixed(1)}</Chip> : null}
                <Chip>{stageLabel(c.stage)}</Chip>
                {c.employees && <Chip>{c.employees.split(/[ (]/)[0]} people</Chip>}
                {c.hq && <Chip>{c.hq}</Chip>}
              </div>
              <div className="flex flex-wrap gap-3 text-[13px]">
                {safeUrl(c.website) && (
                  <a className="text-accent hover:underline" href={safeUrl(c.website)} target="_blank" rel="noreferrer">
                    {c.domain ?? "Website"}
                  </a>
                )}
                <Link to={`/companies/${c.id}`} className="text-accent hover:underline">
                  Full company page
                </Link>
              </div>
            </header>

            <div className="flex flex-col gap-6 p-5">
              <Section title="What they do">
                <p className="text-sm leading-relaxed">{about || "No description yet."}</p>
              </Section>

              {c.open_role && (
                <Section title="The role">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="min-w-0">
                      <p className="font-medium">{c.open_role}</p>
                      {text("salary_verdict") && (
                        <p className="text-[13px] text-muted">{text("salary_verdict").slice(0, 160)}</p>
                      )}
                    </div>
                    {apply && (
                      <div className="flex flex-wrap gap-1">
                        {safeUrl(apply.url ?? c.job_url) && (
                          <a
                            className={linkClass}
                            href={safeUrl(apply.url ?? c.job_url)}
                            target="_blank"
                            rel="noreferrer"
                          >
                            Open posting <ExternalLink size={12} aria-hidden="true" />
                          </a>
                        )}
                        <Button
                          variant="primary"
                          disabled={update.isPending}
                          onClick={() => update.mutate({ id: apply.id, status: "done" })}
                        >
                          <Check size={14} aria-hidden="true" />
                          Applied
                        </Button>
                        <Button
                          variant="quiet"
                          disabled={update.isPending}
                          onClick={() => update.mutate({ id: apply.id, status: "skipped", skip_reason: "Skipped" })}
                        >
                          Skip
                        </Button>
                      </div>
                    )}
                  </div>
                </Section>
              )}

              <Section title={`People (${people.length})`}>
                {people.length ? (
                  <div className="flex flex-col gap-3">
                    {people.map((p) => (
                      <PersonCard key={p.id} person={p} move={reachFor(p.id)} lookup={lookup} />
                    ))}
                  </div>
                ) : (
                  <p className="text-sm text-muted">No one found yet.</p>
                )}
              </Section>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
