import { clsx } from "clsx";
import { ArrowLeft, ExternalLink, Linkedin, Mail, Plus } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";

import {
  type CompanyDetail,
  type MoveType,
  type Person,
  type RoleInHire,
  type Stage,
  type Sureness,
  useAddMove,
  useAddNote,
  useAddPerson,
  useCompany,
  usePromote,
  useReply,
  useUpdateCompany,
  useServerToday,
  useUpdatePerson,
} from "@/api/hooks";
import { MoveRow } from "@/components/MoveRow";
import { Button, Card, Chip, EmptyState } from "@/components/ui";
import {
  LEADERS,
  MOVE_LABEL,
  ROLE_LABEL,
  STAGES,
  STATUS_LABEL,
  SURE_LABEL,
  formatDateTimeDay,
  formatDay,
  formatTime,
  initials,
} from "@/lib/format";

const field = "min-h-[38px] rounded-lg border border-line bg-surface px-3 text-sm";
type Filter = "all" | "local" | "leaders" | "team" | "recruiter";
const FILTERS: [Filter, string][] = [
  ["all", "All"],
  ["local", "In Toronto"],
  ["leaders", "Leaders"],
  ["team", "Team"],
  ["recruiter", "Recruiters"],
];
const LOCAL = /toronto|\bgta\b|mississauga|ontario/i;

function matches(p: Person, f: Filter): boolean {
  if (f === "local") return LOCAL.test(p.location);
  if (f === "leaders") return LEADERS.has(p.role_in_hire);
  if (f === "recruiter") return p.role_in_hire === "recruiter";
  if (f === "team") return p.role_in_hire === "peer or stakeholder" || p.role_in_hire === "poster";
  return true;
}

function Fact({ label, value }: { label: string; value: unknown }) {
  if (typeof value !== "string" || !value) return null;
  return (
    <div className="flex flex-col gap-0.5">
      <dt className="text-[12px] font-medium text-muted">{label}</dt>
      <dd className="text-sm text-ink">{value}</dd>
    </div>
  );
}

function PersonCard({ person }: { person: Person }) {
  const reply = useReply();
  const update = useUpdatePerson();
  const leader = LEADERS.has(person.role_in_hire);
  return (
    <li className={clsx("flex gap-3 px-4 py-3.5", person.left && "opacity-60")}>
      <div
        aria-hidden="true"
        className={clsx(
          "flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-[13px] font-semibold",
          leader ? "bg-accent-tint text-accent-ink" : "bg-good-tint text-good",
        )}
      >
        {initials(person.name)}
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="font-semibold">{person.name}</span>
          <Chip tone={leader ? "accent" : person.role_in_hire === "recruiter" ? "neutral" : "good"}>
            {ROLE_LABEL[person.role_in_hire]}
          </Chip>
          {LOCAL.test(person.location) && <Chip tone="warm">{person.location}</Chip>}
          {person.left && <Chip tone="bad">Left</Chip>}
        </div>
        <p className="text-[13px] text-body">
          {person.title}
          {!LOCAL.test(person.location) && person.location && <span className="text-muted"> · {person.location}</span>}
        </p>
        {person.why && <p className="mt-1 text-[13px] text-muted">{person.why}</p>}
        <div className="mt-2 flex flex-wrap items-center gap-2 text-[13px]">
          {person.sureness && <span className="text-muted">{SURE_LABEL[person.sureness]}</span>}
          <label>
            <span className="sr-only">Status of {person.name}</span>
            <select
              className="rounded-md border border-line bg-surface px-2 py-1 text-[12px]"
              value={person.status}
              onChange={(e) => update.mutate({ id: person.id, status: e.target.value as Person["status"] })}
            >
              {Object.entries(STATUS_LABEL).map(([k, v]) => (
                <option key={k} value={k}>
                  {v}
                </option>
              ))}
            </select>
          </label>
          {person.linkedin && (
            <a
              className="inline-flex items-center gap-1 text-muted hover:text-ink"
              href={person.linkedin}
              target="_blank"
              rel="noreferrer"
            >
              <Linkedin size={13} aria-hidden="true" /> LinkedIn
            </a>
          )}
          {person.email && (
            <a className="inline-flex items-center gap-1 text-muted hover:text-ink" href={`mailto:${person.email}`}>
              <Mail size={13} aria-hidden="true" /> {person.email}
            </a>
          )}
          {person.status !== "replied" && !person.left && (
            <Button
              variant="quiet"
              className="min-h-[30px] px-2 text-[13px]"
              onClick={() => reply.mutate({ id: person.id, text: "" })}
            >
              Log reply
            </Button>
          )}
          {!person.left && (
            <Button
              variant="quiet"
              className="min-h-[30px] px-2 text-[13px]"
              onClick={() => update.mutate({ id: person.id, left: true })}
            >
              They left
            </Button>
          )}
        </div>
      </div>
    </li>
  );
}

function AddPerson({ companyId, onDone }: { companyId: string; onDone: () => void }) {
  const add = useAddPerson();
  const [form, setForm] = useState({ name: "", title: "", linkedin: "", email: "", location: "", why: "" });
  const [role, setRole] = useState<RoleInHire>("hiring manager");
  const [sure, setSure] = useState<Sureness | "">("likely");
  const set = (k: keyof typeof form) => (e: { target: { value: string } }) => setForm({ ...form, [k]: e.target.value });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    add.mutate(
      {
        company_id: companyId,
        name: form.name,
        title: form.title,
        linkedin: form.linkedin || null,
        email: form.email || null,
        location: form.location,
        why: form.why,
        role_in_hire: role,
        sureness: sure || null,
      },
      { onSuccess: onDone },
    );
  };
  return (
    <form
      onSubmit={submit}
      className="grid gap-2 border-t border-line-soft p-4 sm:grid-cols-2"
      aria-label="Add a person"
    >
      <input className={field} placeholder="Name" aria-label="Name" required value={form.name} onChange={set("name")} />
      <input className={field} placeholder="Title" aria-label="Title" value={form.title} onChange={set("title")} />
      <input
        className={field}
        placeholder="LinkedIn URL"
        aria-label="LinkedIn URL"
        type="url"
        value={form.linkedin}
        onChange={set("linkedin")}
      />
      <input
        className={field}
        placeholder="Email"
        aria-label="Email"
        type="email"
        value={form.email}
        onChange={set("email")}
      />
      <input
        className={field}
        placeholder="Location"
        aria-label="Location"
        value={form.location}
        onChange={set("location")}
      />
      <div className="flex gap-2">
        <select
          className={clsx(field, "flex-1")}
          aria-label="Part in the hire"
          value={role}
          onChange={(e) => setRole(e.target.value as RoleInHire)}
        >
          {Object.entries(ROLE_LABEL).map(([k, v]) => (
            <option key={k} value={k}>
              {v}
            </option>
          ))}
        </select>
        <select
          className={field}
          aria-label="How sure"
          value={sure}
          onChange={(e) => setSure(e.target.value as Sureness | "")}
        >
          <option value="">Not sure</option>
          {Object.entries(SURE_LABEL).map(([k, v]) => (
            <option key={k} value={k}>
              {v}
            </option>
          ))}
        </select>
      </div>
      <input
        className={clsx(field, "sm:col-span-2")}
        placeholder="Why them (where this came from)"
        aria-label="Why them"
        value={form.why}
        onChange={set("why")}
      />
      <div className="flex gap-2 sm:col-span-2">
        <Button type="submit" variant="primary" disabled={add.isPending}>
          Add person
        </Button>
        <Button variant="quiet" onClick={onDone}>
          Cancel
        </Button>
      </div>
    </form>
  );
}

function AddMove({ companyId, today }: { companyId: string; today: string }) {
  const add = useAddMove();
  const [title, setTitle] = useState("");
  const [type, setType] = useState<MoveType>("custom");
  const [due, setDue] = useState(today);
  const submit = (e: FormEvent) => {
    e.preventDefault();
    add.mutate({ company_id: companyId, title, type, due }, { onSuccess: () => setTitle("") });
  };
  return (
    <form onSubmit={submit} className="flex flex-wrap gap-2 border-t border-line-soft p-4" aria-label="Add a move">
      <input
        className={clsx(field, "min-w-48 flex-1")}
        placeholder="Add a move"
        aria-label="Move"
        required
        value={title}
        onChange={(e) => setTitle(e.target.value)}
      />
      <select className={field} aria-label="Kind" value={type} onChange={(e) => setType(e.target.value as MoveType)}>
        {Object.entries(MOVE_LABEL)
          .filter(([k]) => k !== "reach")
          .map(([k, v]) => (
            <option key={k} value={k}>
              {v}
            </option>
          ))}
      </select>
      <input className={field} type="date" aria-label="Due" value={due} onChange={(e) => setDue(e.target.value)} />
      <Button type="submit" variant="secondary" disabled={add.isPending}>
        <Plus size={14} aria-hidden="true" /> Add
      </Button>
    </form>
  );
}

function Notes({ company }: { company: CompanyDetail }) {
  const update = useUpdateCompany();
  const [notes, setNotes] = useState(company.notes);
  const dirty = notes !== company.notes;
  return (
    <Card className="flex flex-col gap-2 p-4">
      <label htmlFor="notes" className="text-[15px] font-semibold">
        Notes
      </label>
      <textarea
        id="notes"
        className="min-h-28 rounded-lg border border-line p-3 text-sm"
        value={notes}
        onChange={(e) => setNotes(e.target.value)}
        onBlur={() => dirty && update.mutate({ id: company.id, notes })}
      />
      <span className="text-[12px] text-muted">
        {update.isPending ? "Saving…" : dirty ? "Saves when you click away" : "Saved"}
      </span>
    </Card>
  );
}

export function CompanyPage() {
  const { id = "" } = useParams();
  const { data: c, isPending, isError } = useCompany(id);
  const update = useUpdateCompany();
  const promote = usePromote();
  const note = useAddNote();
  const [filter, setFilter] = useState<Filter>("all");
  const [adding, setAdding] = useState(false);
  const [noteText, setNoteText] = useState("");
  const today = useServerToday();

  if (isPending) return <p className="text-sm text-muted">Loading…</p>;
  if (isError || !c) return <EmptyState title="That company isn't in the tracker">Go back to the pipeline.</EmptyState>;

  const research = c.research;
  const shown = c.people.filter((p) => matches(p, filter));
  const open = c.moves.filter((m) => m.status === "open");
  const finished = c.moves.filter((m) => m.status !== "open");
  const cards = (ms: typeof c.moves) =>
    ms.map((m) => ({ ...m, company: c, person: c.people.find((p) => p.id === m.person_id) ?? null }));

  return (
    <div className="flex max-w-6xl flex-col gap-6">
      <Link
        to="/pipeline"
        className="inline-flex w-fit items-center gap-1.5 text-sm font-medium text-muted hover:text-ink"
      >
        <ArrowLeft size={15} aria-hidden="true" /> Pipeline
      </Link>
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex items-center gap-3">
          <div
            aria-hidden="true"
            className="flex h-12 w-12 items-center justify-center rounded-xl bg-ink text-lg font-bold text-white"
          >
            {c.name[0]}
          </div>
          <div>
            <h1 className="text-[26px] font-bold tracking-tight">{c.name}</h1>
            <p className="text-sm text-muted">
              {[research["one_liner"], c.employees && `${c.employees} people`, c.hq].filter(Boolean).join(" · ")}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {c.stage === "bench" && (
            <Button
              variant="primary"
              disabled={promote.isPending}
              onClick={() => promote.mutate({ id: c.id, wave: "2" })}
            >
              Take off the bench
            </Button>
          )}
          <label className="flex items-center gap-2 text-sm text-muted">
            Stage
            <select
              className={field}
              value={c.stage}
              onChange={(e) => update.mutate({ id: c.id, stage: e.target.value as Stage })}
            >
              {STAGES.map((s) => (
                <option key={s.key} value={s.key}>
                  {s.label}
                </option>
              ))}
            </select>
          </label>
        </div>
      </header>
      {c.parked_reason && <p className="rounded-lg bg-warm-tint px-4 py-3 text-sm text-warm">{c.parked_reason}</p>}

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_340px]">
        <div className="flex min-w-0 flex-col gap-6">
          <Card className="flex flex-col gap-3 p-5">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <h2 className="text-lg font-semibold">{c.open_role ?? "No open role yet"}</h2>
                {c.posted && <p className="text-[13px] text-muted">Posted {formatDay(c.posted)}</p>}
              </div>
              {c.job_url && (
                <a
                  className="inline-flex items-center gap-1.5 text-sm font-medium text-accent hover:underline"
                  href={c.job_url}
                  target="_blank"
                  rel="noreferrer"
                >
                  Open posting <ExternalLink size={14} aria-hidden="true" />
                </a>
              )}
            </div>
            {typeof research["what_the_role_is"] === "string" && (
              <p className="text-sm text-body">{research["what_the_role_is"]}</p>
            )}
            {typeof research["watch_out"] === "string" && (
              <p className="text-sm text-body">
                <span className="font-semibold text-warm">Watch out: </span>
                {research["watch_out"]}
              </p>
            )}
            <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <Fact label="Pay" value={research["salary"]} />
              <Fact label="Where" value={research["where"]} />
              <Fact label="Fit" value={research["fit"]} />
              <Fact label="Region" value={c.region} />
            </dl>
          </Card>

          <Card>
            <div className="flex flex-wrap items-center justify-between gap-3 px-4 pt-4">
              <div>
                <h2 className="text-[15px] font-semibold">People around this role</h2>
                <p className="text-[13px] text-muted">
                  {shown.length} of {c.people.length} · warmest first
                </p>
              </div>
              <div className="flex flex-wrap gap-1.5" role="group" aria-label="Show">
                {FILTERS.map(([key, label]) => (
                  <button
                    key={key}
                    type="button"
                    aria-pressed={filter === key}
                    onClick={() => setFilter(key)}
                    className={clsx(
                      "min-h-[32px] rounded-full px-3 text-[13px] font-medium",
                      filter === key ? "bg-ink text-white" : "border border-line text-body hover:bg-chip",
                    )}
                  >
                    {label}
                  </button>
                ))}
              </div>
            </div>
            {shown.length ? (
              <ul className="mt-2 divide-y divide-line-soft">
                {shown.map((p) => (
                  <PersonCard key={p.id} person={p} />
                ))}
              </ul>
            ) : (
              <p className="px-4 py-6 text-sm text-muted">No one here yet.</p>
            )}
            {adding ? (
              <AddPerson companyId={c.id} onDone={() => setAdding(false)} />
            ) : (
              <div className="border-t border-line-soft p-3">
                <Button variant="quiet" onClick={() => setAdding(true)}>
                  <Plus size={14} aria-hidden="true" /> Add a person
                </Button>
              </div>
            )}
          </Card>

          <Card>
            <h2 className="px-4 pt-4 text-[15px] font-semibold">Moves</h2>
            {open.length ? (
              <div className="mt-2 divide-y divide-line-soft">
                {cards(open).map((m) => (
                  <MoveRow key={m.id} move={m} today={today} />
                ))}
              </div>
            ) : (
              <p className="px-4 py-4 text-sm text-muted">Nothing open.</p>
            )}
            <AddMove companyId={c.id} today={today} />
            {finished.length > 0 && (
              <details className="border-t border-line-soft">
                <summary className="cursor-pointer px-4 py-3 text-sm font-medium text-muted">
                  {finished.length} finished
                </summary>
                <div className="divide-y divide-line-soft">
                  {cards(finished).map((m) => (
                    <MoveRow key={m.id} move={m} today={today} compact />
                  ))}
                </div>
              </details>
            )}
          </Card>
        </div>

        <aside className="flex flex-col gap-6">
          <Notes key={c.id + c.notes} company={c} />
          <Card className="flex flex-col gap-3 p-4">
            <h2 className="text-[15px] font-semibold">History</h2>
            <form
              className="flex gap-2"
              onSubmit={(e) => {
                e.preventDefault();
                note.mutate({ text: noteText, company_id: c.id }, { onSuccess: () => setNoteText("") });
              }}
            >
              <input
                className={clsx(field, "flex-1")}
                placeholder="Add a note"
                aria-label="Add a note"
                required
                value={noteText}
                onChange={(e) => setNoteText(e.target.value)}
              />
              <Button type="submit" disabled={note.isPending}>
                Add
              </Button>
            </form>
            <ol className="flex flex-col gap-2.5">
              {c.activity.map((a) => (
                <li key={a.id} className="text-[13px]">
                  <p className="text-body">{a.text}</p>
                  <p className="text-muted">
                    {formatDateTimeDay(a.at)} · {formatTime(a.at)}
                    {a.xp > 0 && ` · +${a.xp} XP`}
                  </p>
                </li>
              ))}
            </ol>
          </Card>
        </aside>
      </div>
    </div>
  );
}
