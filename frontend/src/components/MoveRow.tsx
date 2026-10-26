import { clsx } from "clsx";
import { Check, Copy, ExternalLink, Linkedin, Mail, MessageSquareReply } from "lucide-react";
import { Link } from "react-router-dom";

import { type MoveCard, type Person, type S, type Step, useReply, useTickStep, useUpdateMove } from "@/api/hooks";
import { notify } from "@/components/Toast";
import { Button, Chip } from "@/components/ui";
import { MOVE_LABEL, ROLE_LABEL, SURE_LABEL, formatDay, nextWorkday } from "@/lib/format";
import { safeUrl } from "@/lib/safe";

type Draft = S["Draft"];

const STEP_BUTTON: Record<string, { step: Step; label: string; done: string }> = {
  email: { step: "email", label: "Emailed", done: "Emailed" },
  request: { step: "request", label: "Request sent", done: "Request sent" },
  dm: { step: "dm", label: "Message sent", done: "Message sent" },
  bump: { step: "bump", label: "Bumped", done: "Bumped" },
};
export const COPY_FOR: Record<string, { draft: string[]; label: string }> = {
  email: { draft: ["email_day0", "email_day0_b"], label: "Copy email" },
  request: { draft: ["li_note"], label: "Copy note" },
  bump: { draft: ["bump", "email_day3"], label: "Copy bump" },
};

export async function copy(draft: Draft, what: string) {
  const text = draft.subject ? `${draft.subject}\n\n${draft.body}` : draft.body;
  try {
    await navigator.clipboard.writeText(text);
    notify(`${what} copied`);
  } catch {
    notify("Couldn't copy. Select the text and copy it instead.", "error");
  }
}

export function findDraft(person: Person | null | undefined, types: string[]): Draft | undefined {
  const drafts = person?.drafts ?? [];
  const variant = person?.ab_variant === "B" ? ["email_day0_b"] : [];
  for (const type of [...variant, ...types]) {
    const d = drafts.find((x) => x.type === type);
    if (d) return d;
  }
  return undefined;
}

function headline(move: MoveCard): string {
  const who = move.person?.name;
  if (move.type !== "reach" || !who) return move.title;
  const next = move.sequence?.next ?? "";
  if (next.includes("email") && next.includes("request")) return `Email and connect with ${who}`;
  if (next.includes("email")) return `Email ${who}`;
  if (next.includes("request")) return `Connect with ${who}`;
  if (next === "dm") return `Message ${who} on LinkedIn`;
  if (next === "bump") return `Bump ${who}`;
  return `Reach out to ${who}`;
}

function isLocal(location: string | undefined) {
  return !!location && /toronto|\bgta\b|mississauga|ontario/i.test(location);
}

export function MoveRow({ move, today, compact = false }: { move: MoveCard; today: string; compact?: boolean }) {
  const tick = useTickStep();
  const update = useUpdateMove();
  const reply = useReply();
  const busy = tick.isPending || update.isPending || reply.isPending;
  const person = move.person;
  const company = move.company;
  const pending = move.type === "reach" && move.status === "open" ? (move.sequence?.next ?? "").split("+") : [];
  const steps = move.sequence?.steps ?? {};
  const overdue = move.status === "open" && move.due < today;

  const later = () => update.mutate({ id: move.id, due: nextWorkday(today) });

  return (
    // the text keeps a readable width; when the buttons don't fit beside it they wrap onto their own line below
    <article className={clsx("flex flex-wrap items-center gap-x-4 gap-y-2.5 px-4 py-3.5", compact && "py-3")}>
      <div className="min-w-0 flex-1 basis-80">
        <p className="text-[15px] leading-snug">
          <span className="font-semibold text-ink">{headline(move)}</span>
          {person && <span className="text-muted"> · {person.title}</span>}
          {company && (
            <>
              <span className="text-muted">, </span>
              <Link
                to={`/companies/${company.id}`}
                className="text-muted underline-offset-2 hover:text-ink hover:underline"
              >
                {company.name}
              </Link>
            </>
          )}
        </p>
        <div className="mt-1 flex flex-wrap items-center gap-1.5 text-[13px] text-muted">
          {move.type !== "reach" && <Chip>{MOVE_LABEL[move.type]}</Chip>}
          {person && <Chip tone="accent">{ROLE_LABEL[person.role_in_hire]}</Chip>}
          {person?.sureness && <span>{SURE_LABEL[person.sureness]}</span>}
          {isLocal(person?.location) && <Chip tone="warm">Toronto</Chip>}
          {person?.left && <Chip tone="bad">Left the company</Chip>}
          {overdue && <Chip>From {formatDay(move.due)}</Chip>}
          {move.type === "apply" && company?.open_role && <span>{company.open_role}</span>}
          {steps.email && steps.email !== "na" && !pending.includes("email") && (
            <span>Emailed {formatDay(steps.email)}</span>
          )}
          {move.status === "done" && move.type !== "reach" && <Chip tone="good">Done</Chip>}
        </div>
      </div>

      {!compact && move.status === "open" && (
        <div className="flex min-w-0 max-w-full flex-wrap items-center gap-2">
          {move.type === "reach" ? (
            <>
              {pending.map((p) => {
                const c = COPY_FOR[p];
                const draft = c && findDraft(move.person, c.draft);
                return draft ? (
                  <Button
                    key={`copy-${p}`}
                    variant="quiet"
                    onClick={() => void copy(draft, c.label.replace("Copy ", ""))}
                  >
                    <Copy size={14} aria-hidden="true" />
                    {c.label}
                  </Button>
                ) : null;
              })}
              {pending.includes("email") && person?.email && (
                <a
                  className="inline-flex min-h-[38px] items-center gap-1.5 rounded-lg px-3 text-sm font-medium text-muted hover:bg-chip hover:text-ink"
                  href={`mailto:${person.email}`}
                >
                  <Mail size={14} aria-hidden="true" />
                  Open email
                </a>
              )}
              {(pending.includes("request") || pending.includes("dm")) && safeUrl(person?.linkedin) && (
                <a
                  className="inline-flex min-h-[38px] items-center gap-1.5 rounded-lg px-3 text-sm font-medium text-muted hover:bg-chip hover:text-ink"
                  href={safeUrl(person?.linkedin)}
                  target="_blank"
                  rel="noreferrer"
                >
                  <Linkedin size={14} aria-hidden="true" />
                  LinkedIn
                </a>
              )}
              {pending.map((p, i) => {
                const b = STEP_BUTTON[p];
                return b ? (
                  <Button
                    key={p}
                    variant={i === 0 ? "primary" : "secondary"}
                    disabled={busy}
                    onClick={() => tick.mutate({ id: move.id, step: b.step })}
                  >
                    <Check size={14} aria-hidden="true" />
                    {b.label}
                  </Button>
                ) : null;
              })}
              {pending.includes("email") && !person?.email && (
                <Button
                  variant="quiet"
                  disabled={busy}
                  onClick={() => tick.mutate({ id: move.id, step: "email", value: "na" })}
                >
                  No email
                </Button>
              )}
              {pending.includes("bump") && steps.request && steps.request !== "na" && !steps.accepted && (
                <Button disabled={busy} onClick={() => tick.mutate({ id: move.id, step: "accepted" })}>
                  They accepted
                </Button>
              )}
              {person && (
                <Button variant="quiet" disabled={busy} onClick={() => reply.mutate({ id: person.id, text: "" })}>
                  <MessageSquareReply size={14} aria-hidden="true" />
                  Replied
                </Button>
              )}
            </>
          ) : (
            <>
              {safeUrl(move.url) && (
                <a
                  className="inline-flex min-h-[38px] items-center gap-1.5 rounded-lg px-3 text-sm font-medium text-muted hover:bg-chip hover:text-ink"
                  href={safeUrl(move.url)}
                  target="_blank"
                  rel="noreferrer"
                >
                  <ExternalLink size={14} aria-hidden="true" />
                  {move.type === "apply" ? "Open posting" : "Open link"}
                </a>
              )}
              <Button variant="primary" disabled={busy} onClick={() => update.mutate({ id: move.id, status: "done" })}>
                <Check size={14} aria-hidden="true" />
                {move.type === "apply" ? "Applied" : "Done"}
              </Button>
              {move.type === "apply" && (
                <Button
                  variant="quiet"
                  disabled={busy}
                  title="Skip without passing on the company"
                  onClick={() => update.mutate({ id: move.id, status: "skipped", skip_reason: "US only" })}
                >
                  US only
                </Button>
              )}
              <Button variant="quiet" disabled={busy} onClick={() => update.mutate({ id: move.id, status: "skipped" })}>
                Skip
              </Button>
            </>
          )}
          <Button variant="quiet" disabled={busy} onClick={later}>
            Later
          </Button>
        </div>
      )}
    </article>
  );
}
