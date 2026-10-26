import { clsx } from "clsx";
import { Check, Copy, ExternalLink, Linkedin, X } from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";

import { type ProspectDetail, type S, useFxProspect, useUpdateProspect } from "@/api/hooks";
import { notify } from "@/components/Toast";
import { Button, Chip } from "@/components/ui";
import { formatDay, initials, nextWorkday } from "@/lib/format";
import { safeUrl, strings } from "@/lib/safe";

type Tab = "plan" | "research" | "notes";
type Touch = "connect" | "dm" | "email";
type Step = S["StepChange"]["name"];

const TOUCHES: { kind: Touch; label: string; xp: number }[] = [
  { kind: "connect", label: "Request", xp: 2 },
  { kind: "dm", label: "DM", xp: 3 },
  { kind: "email", label: "Email", xp: 3 },
];
const CLOSE_STEPS: { step: Step; label: string; hint: string; xp: number }[] = [
  { step: "fu1", label: "Follow-up 1", hint: "3 working days after your first message", xp: 2 },
  { step: "fu2", label: "Follow-up 2", hint: "4 working days after follow-up 1. Then let it rest", xp: 2 },
  { step: "replied", label: "They replied", hint: "Any reply counts, even a no", xp: 10 },
  { step: "call", label: "Call booked", hint: "Discovery call on the calendar", xp: 25 },
  { step: "proposal", label: "Proposal sent", hint: "Scope, price and start date", xp: 40 },
  { step: "won", label: "Signed as a client", hint: "$3K a month", xp: 100 },
];
const SAVE_DELAY_MS = 600;
const NOTE_LIMIT = 200;

/** Lower-case the first letter of a sentence that will sit mid-sentence ("A list" -> "a list"), not of an acronym. */
function lcFirst(text: string): string {
  return /^(A\s|[A-Z][a-z])/.test(text) ? text.charAt(0).toLowerCase() + text.slice(1) : text;
}

export function template(p: ProspectDetail): string {
  const first = p.people[0]?.name.split(/\s+/)[0] ?? "there";
  const hook = strings(p.research["interview_hooks"])[0] ?? "";
  const lines = [
    "LinkedIn request (keep it under 200 characters):",
    `Hi ${first}, I build outbound systems for seed and Series A teams and had an idea for ${p.name}'s pipeline. Would like to connect.`,
    "",
    "DM once they accept:",
    hook,
    p.pvp ? `I'm a GTM engineer in Toronto. I put together ${lcFirst(p.pvp)}, free. Want me to send it?` : "",
    "",
    "Email:",
    `Subject: ${p.name} pipeline idea`,
    `Hi ${first},`,
    hook,
    p.offer ? `That's the kind of system I build as a fractional GTM engineer: ${lcFirst(p.offer)}.` : "",
    p.pvp ? `I made ${lcFirst(p.pvp)}. Want me to send it over?` : "",
  ];
  return lines.filter((line, i) => line !== "" || lines[i - 1] !== "").join("\n");
}

function KeyValue({ label, value }: { label: string; value: ReactNode }) {
  if (!value) return null;
  return (
    <div className="flex flex-col gap-0.5">
      <dt className="text-[12px] font-medium text-muted">{label}</dt>
      <dd className="text-sm text-ink">{value}</dd>
    </div>
  );
}

async function copy(text: string) {
  try {
    await navigator.clipboard.writeText(text);
    notify("Copied");
  } catch {
    notify("Couldn't copy in this browser. Select the text and copy it instead.", "error");
  }
}

function Checklist({ p, today }: { p: ProspectDetail; today: string }) {
  const update = useUpdateProspect();
  const busy = update.isPending;
  const first = p.first_touch;
  return (
    <div className="flex flex-col gap-5">
      <dl className="grid gap-3">
        <KeyValue label="Why now" value={p.why_now} />
        <KeyValue label="Your offer" value={p.offer} />
        <KeyValue label="Free first thing to build for them" value={p.pvp} />
        <KeyValue label="The problem you solve" value={p.research["pain_hypothesis"] as string | undefined} />
        <KeyValue label="Fit note" value={p.fit_reason} />
      </dl>

      <label className="flex items-start gap-3 rounded-lg border border-line p-3">
        <input
          type="checkbox"
          className="mt-1"
          checked={!!p.steps["researched"]}
          disabled={busy}
          onChange={(e) => update.mutate({ id: p.id, step: { name: "researched", on: e.target.checked } })}
        />
        <span>
          <span className="block text-sm font-semibold">Read the dossier</span>
          <span className="text-[13px] text-muted">Know what they sell, who buys and the angle before you write.</span>
        </span>
      </label>

      <section aria-labelledby="reach-out" className="flex flex-col gap-2">
        <h3 id="reach-out" className="text-[15px] font-semibold">
          Reach out
        </h3>
        <p className="text-[13px] text-muted">
          Tick each message the moment you send it. Your first one makes this company a hit for today.
        </p>
        {p.people.length === 0 && <p className="text-sm text-muted">No people yet.</p>}
        {p.people.map((person) => (
          <div key={person.key} className="flex flex-wrap items-center gap-3 rounded-lg border border-line p-3">
            <div
              aria-hidden="true"
              className="flex h-8 w-8 items-center justify-center rounded-full bg-accent-tint text-[12px] font-semibold text-accent-ink"
            >
              {initials(person.name)}
            </div>
            <div className="min-w-0 flex-1">
              <p className="text-sm font-semibold">{person.name}</p>
              <p className="text-[13px] text-muted">{[person.title, person.location].filter(Boolean).join(" · ")}</p>
            </div>
            {safeUrl(person.linkedin) && (
              <a
                href={safeUrl(person.linkedin)}
                target="_blank"
                rel="noreferrer"
                aria-label={`${person.name} on LinkedIn`}
              >
                <Linkedin size={16} className="text-muted hover:text-ink" aria-hidden="true" />
              </a>
            )}
            <div className="flex gap-1.5">
              {TOUCHES.map(({ kind, label, xp }) => {
                const sent = p.touches[person.key]?.[kind];
                return (
                  <button
                    key={kind}
                    type="button"
                    aria-pressed={!!sent}
                    disabled={busy}
                    onClick={() => update.mutate({ id: p.id, touch: { person: person.key, kind, on: !sent } })}
                    className={clsx(
                      "min-h-[34px] rounded-lg px-2.5 text-[13px] font-medium",
                      sent ? "bg-good-tint text-good" : "border border-line text-body hover:bg-chip",
                    )}
                  >
                    {label}
                    <span className="ml-1 text-[12px] opacity-80">{sent ? `Sent ${formatDay(sent)}` : `+${xp}`}</span>
                  </button>
                );
              })}
            </div>
          </div>
        ))}
      </section>

      <section aria-labelledby="close" className="flex flex-col gap-2">
        <h3 id="close" className="text-[15px] font-semibold">
          Follow up and close
        </h3>
        {CLOSE_STEPS.map(({ step, label, hint, xp }) => {
          const done = p.steps[step];
          const due = p.follow_up?.step === step ? p.follow_up.due : null;
          const waiting = (step === "fu1" || step === "fu2") && !first;
          return (
            <label key={step} className="flex items-start gap-3 rounded-lg border border-line p-3">
              <input
                type="checkbox"
                className="mt-1"
                checked={!!done}
                disabled={busy || waiting}
                onChange={(e) => update.mutate({ id: p.id, step: { name: step, on: e.target.checked } })}
              />
              <span className="flex-1">
                <span className="block text-sm font-semibold">{label}</span>
                <span className={clsx("text-[13px]", due && due < today ? "text-bad" : "text-muted")}>
                  {done
                    ? `Done ${formatDay(done)}`
                    : waiting
                      ? "Starts after your first message"
                      : due
                        ? `Due ${formatDay(due)}`
                        : hint}
                </span>
              </span>
              {!done && <Chip tone="accent">+{xp} XP</Chip>}
            </label>
          );
        })}
      </section>

      <div className="flex flex-wrap gap-2 border-t border-line-soft pt-4">
        {p.status === "open" ? (
          <>
            {p.stage === "untouched" && p.effective_day <= today && (
              <Button disabled={busy} onClick={() => update.mutate({ id: p.id, day_override: nextWorkday(today) })}>
                Move to {formatDay(nextWorkday(today))}
              </Button>
            )}
            {p.stage === "untouched" && p.effective_day > today && (
              <Button disabled={busy} onClick={() => update.mutate({ id: p.id, day_override: today })}>
                Do it today
              </Button>
            )}
            <Button variant="quiet" disabled={busy} onClick={() => update.mutate({ id: p.id, status: "skipped" })}>
              Skip: not a fit
            </Button>
            <Button
              variant="quiet"
              className="text-bad"
              disabled={busy}
              onClick={() => {
                const reason = window.prompt("Why was it lost? (optional)", "");
                if (reason !== null) update.mutate({ id: p.id, status: "lost", lost_reason: reason });
              }}
            >
              Mark lost
            </Button>
          </>
        ) : (
          <Button disabled={busy} onClick={() => update.mutate({ id: p.id, status: "open" })}>
            Reopen
          </Button>
        )}
      </div>
    </div>
  );
}

function List({ title, items }: { title: string; items: unknown }) {
  const list = strings(items);
  if (!list.length) return null;
  return (
    <section className="flex flex-col gap-2">
      <h3 className="text-[15px] font-semibold">{title}</h3>
      <ul className="flex flex-col gap-1.5">
        {list.map((item) => (
          <li key={item} className="flex items-start gap-2 text-sm text-body">
            <span className="flex-1">{item}</span>
            <button
              type="button"
              aria-label="Copy"
              className="text-muted hover:text-ink"
              onClick={() => void copy(item)}
            >
              <Copy size={14} aria-hidden="true" />
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}

function Research({ p }: { p: ProspectDetail }) {
  const r = p.research;
  const text = (k: string) => (typeof r[k] === "string" ? (r[k] as string) : undefined);
  const competitors = strings(r["competitors"]);
  const sources = strings(r["sources"]);
  return (
    <div className="flex flex-col gap-5">
      <section>
        <h3 className="text-[15px] font-semibold">What they do</h3>
        <p className="text-sm text-body">{text("one_liner")}</p>
        {text("value_prop") && <p className="mt-1 text-sm text-muted">{text("value_prop")}</p>}
      </section>
      <dl className="grid gap-3 sm:grid-cols-2">
        <KeyValue label="Who buys" value={text("buyer")} />
        <KeyValue label="How they sell" value={text("gtm_motion")} />
        <KeyValue label="Their GTM team today" value={text("gtm_team")} />
        <KeyValue label="Traction" value={text("traction")} />
        <KeyValue label="Pricing" value={text("pricing")} />
        <KeyValue label="Recent news" value={text("recent")} />
        <KeyValue label="Tools you can see" value={text("stack_hints")} />
        <KeyValue
          label="Their email setup"
          value={`${p.dmarc ? `DMARC ${p.dmarc}` : "No DMARC"} · SPF ${p.spf || "unknown"}`}
        />
      </dl>
      {competitors.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {competitors.map((c) => (
            <Chip key={c}>{c}</Chip>
          ))}
        </div>
      )}
      <List title="Openers that earn a reply" items={r["interview_hooks"]} />
      <List title="Questions for the call" items={r["questions"]} />
      {sources.length > 0 && (
        <section className="flex flex-col gap-1">
          <h3 className="text-[15px] font-semibold">Sources</h3>
          {sources.map((s) => {
            const href = safeUrl(s);
            const label = s.length > 70 ? `${s.slice(0, 70)}…` : s;
            return href ? (
              <a
                key={s}
                href={href}
                target="_blank"
                rel="noreferrer"
                className="truncate text-[13px] text-accent hover:underline"
              >
                {label}
              </a>
            ) : (
              <span key={s} className="truncate text-[13px] text-muted">
                {label}
              </span>
            );
          })}
        </section>
      )}
    </div>
  );
}

/** A text field that saves itself shortly after you stop typing, and before the drawer closes. */
function AutosaveField({
  p,
  field,
  label,
  placeholder,
  rows,
  value,
  onChange,
}: {
  p: ProspectDetail;
  field: "draft" | "my_notes";
  label: string;
  placeholder: string;
  rows: number;
  value: string;
  onChange: (v: string) => void;
}) {
  const update = useUpdateProspect();
  const saved = useRef(p[field]);
  const latest = useRef(value);
  latest.current = value;
  const [state, setState] = useState<"saved" | "saving" | "error">("saved");

  useEffect(() => {
    if (value === saved.current) return;
    const timer = window.setTimeout(() => {
      setState("saving");
      update.mutate(
        { id: p.id, [field]: value },
        {
          onSuccess: () => {
            saved.current = value;
            setState("saved");
          },
          onError: () => setState("error"),
        },
      );
    }, SAVE_DELAY_MS);
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- save when the text changes, not when the mutation does
  }, [value, p.id, field]);

  useEffect(
    () => () => {
      // closing or switching prospects: save what's unsaved right away
      if (latest.current !== saved.current) update.mutate({ id: p.id, [field]: latest.current });
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps -- once per prospect and field
    [p.id, field],
  );

  return (
    <label className="flex flex-col gap-1.5">
      <span className="text-[15px] font-semibold">{label}</span>
      <textarea
        className="rounded-lg border border-line p-3 text-sm"
        rows={rows}
        placeholder={placeholder}
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
      <span className={clsx("text-[12px]", state === "error" ? "text-bad" : "text-muted")}>
        {state === "saving" ? "Saving…" : state === "error" ? "Not saved. Check your connection." : "Saves as you type"}
      </span>
    </label>
  );
}

function Notes({ p }: { p: ProspectDetail }) {
  const [draft, setDraft] = useState(p.draft);
  const [notes, setNotes] = useState(p.my_notes);
  const firstParagraph = (draft.split(/\n\s*\n/)[0] ?? "").replace(/^LinkedIn request.*\n?/i, "").trim();
  const hooks = strings(p.research["interview_hooks"]);
  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap gap-2">
        <Button
          onClick={() => {
            if (!draft || window.confirm("Replace your draft with the template?")) setDraft(template(p));
          }}
        >
          Start from a template
        </Button>
        {hooks.map((hook, i) => (
          <Button key={hook} variant="quiet" title={hook} onClick={() => setDraft(draft ? `${draft}\n${hook}` : hook)}>
            Insert opener {i + 1}
          </Button>
        ))}
      </div>
      <AutosaveField
        p={p}
        field="draft"
        label="Draft message"
        placeholder="Write it here. It saves as you type."
        rows={10}
        value={draft}
        onChange={setDraft}
      />
      <p className={clsx("-mt-3 text-[12px]", firstParagraph.length > NOTE_LIMIT ? "text-bad" : "text-muted")}>
        {draft.length} characters · first paragraph {firstParagraph.length} (LinkedIn request notes: 200, or 300 with
        Premium)
      </p>
      <AutosaveField
        p={p}
        field="my_notes"
        label="Your notes"
        placeholder="What they said, objections, next steps"
        rows={6}
        value={notes}
        onChange={setNotes}
      />
    </div>
  );
}

const FOCUSABLE =
  "a[href], button:not([disabled]), input:not([disabled]), textarea:not([disabled]), select:not([disabled])";

/** Keep Tab inside the dialog: past the last control it wraps to the first, and back. */
function trapTab(e: KeyboardEvent, panel: HTMLElement) {
  const items = [...panel.querySelectorAll<HTMLElement>(FOCUSABLE)];
  const first = items[0];
  const last = items[items.length - 1];
  if (!first || !last) return;
  const at = document.activeElement;
  if (e.shiftKey && (at === first || at === panel)) {
    e.preventDefault();
    last.focus();
  } else if (!e.shiftKey && (at === last || !panel.contains(at))) {
    e.preventDefault();
    first.focus();
  }
}

export function ProspectDrawer({ id, today, onClose }: { id: string; today: string; onClose: () => void }) {
  const { data: p, isPending, isError } = useFxProspect(id);
  const [tab, setTab] = useState<Tab>(() => {
    try {
      return (localStorage.getItem("fx-tab") as Tab | null) ?? "plan";
    } catch {
      return "plan";
    }
  });
  const panel = useRef<HTMLDivElement>(null);
  const close = useRef(onClose);
  useEffect(() => {
    close.current = onClose;
  });

  // Once per opening: the parent passes a new onClose on every render, which must not move focus around.
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

  const pick = (t: Tab) => {
    setTab(t);
    try {
      localStorage.setItem("fx-tab", t);
    } catch {
      // storage may be unavailable (private mode); the tab just isn't remembered
    }
  };

  return (
    <div className="fixed inset-0 z-40 flex justify-end">
      <button type="button" aria-label="Close" tabIndex={-1} className="absolute inset-0 bg-ink/30" onClick={onClose} />
      <div
        ref={panel}
        role="dialog"
        aria-modal="true"
        aria-label={p?.name ?? "Prospect"}
        tabIndex={-1}
        className="relative flex h-full w-full max-w-xl flex-col overflow-y-auto bg-surface shadow-2xl outline-none"
      >
        {isPending ? (
          <p className="p-6 text-sm text-muted">Loading…</p>
        ) : isError || !p ? (
          <p className="p-6 text-sm text-bad">Couldn't load this prospect.</p>
        ) : (
          <>
            <header className="flex flex-col gap-3 border-b border-line p-5">
              <div className="flex items-start justify-between gap-3">
                <div className="flex items-center gap-3">
                  <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-chip text-[13px] font-semibold">
                    {p.first_touch ? <Check size={15} aria-label="Reached" /> : p.rank}
                  </span>
                  <h2 className="text-xl font-bold">{p.name}</h2>
                </div>
                <button type="button" aria-label="Close" onClick={onClose} className="rounded p-1 hover:bg-chip">
                  <X size={18} aria-hidden="true" />
                </button>
              </div>
              <div className="flex flex-wrap gap-1.5">
                {p.round && <Chip>{p.round}</Chip>}
                {p.hq && <Chip>{p.hq}</Chip>}
                {p.employees && <Chip>{p.employees} people</Chip>}
                <Chip tone={p.dmarc && p.dmarc !== "none" && p.dmarc !== "missing" ? "neutral" : "warm"}>
                  {p.dmarc && p.dmarc !== "missing" ? `DMARC ${p.dmarc}` : "No DMARC"}
                </Chip>
                <Chip tone="accent">{p.xp} XP</Chip>
                {p.status !== "open" && <Chip tone={p.status === "won" ? "good" : "bad"}>{p.status}</Chip>}
              </div>
              <div className="flex flex-wrap gap-3 text-[13px]">
                {safeUrl(p.website) && (
                  <a
                    className="inline-flex items-center gap-1 text-accent hover:underline"
                    href={safeUrl(p.website)}
                    target="_blank"
                    rel="noreferrer"
                  >
                    {p.domain ?? p.website} <ExternalLink size={12} aria-hidden="true" />
                  </a>
                )}
                {safeUrl(p.linkedin) && (
                  <a
                    className="text-accent hover:underline"
                    href={safeUrl(p.linkedin)}
                    target="_blank"
                    rel="noreferrer"
                  >
                    Company page
                  </a>
                )}
                <a
                  className="text-accent hover:underline"
                  href={`https://www.linkedin.com/search/results/people/?keywords=${encodeURIComponent(p.name)}`}
                  target="_blank"
                  rel="noreferrer"
                >
                  Find more people
                </a>
              </div>
              <div role="tablist" aria-label="Sections" className="flex gap-1">
                {(
                  [
                    ["plan", "Checklist"],
                    ["research", "Research"],
                    ["notes", "Notes"],
                  ] as const
                ).map(([key, label]) => (
                  <button
                    key={key}
                    type="button"
                    role="tab"
                    aria-selected={tab === key}
                    onClick={() => pick(key)}
                    className={clsx(
                      "min-h-[34px] rounded-lg px-3 text-sm font-medium",
                      tab === key ? "bg-accent-tint text-accent-ink" : "text-muted hover:bg-chip",
                    )}
                  >
                    {label}
                  </button>
                ))}
              </div>
            </header>
            <div role="tabpanel" className="p-5">
              {tab === "plan" && <Checklist p={p} today={today} />}
              {tab === "research" && <Research p={p} />}
              {tab === "notes" && <Notes key={p.id} p={p} />}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
