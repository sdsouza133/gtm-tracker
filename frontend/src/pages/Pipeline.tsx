import {
  DndContext,
  KeyboardSensor,
  PointerSensor,
  useDraggable,
  useDroppable,
  useSensor,
  useSensors,
  type DragEndEvent,
} from "@dnd-kit/core";
import { clsx } from "clsx";
import { Plus, Search } from "lucide-react";
import { useDeferredValue, useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";

import { type CompanySummary, type Stage, useAddCompany, useCompanies, useMoveCompany } from "@/api/hooks";
import { Button, Card, EmptyState, PageHeader } from "@/components/ui";
import { STAGES, formatDay, stageLabel } from "@/lib/format";

const BOARD: Stage[] = [
  "not_started",
  "researching",
  "contacted",
  "replied",
  "call_booked",
  "interviewing",
  "take_home",
  "offer",
];
const PAUSED: Stage[] = ["parked", "rejected", "bench"];

function CompanyCard({ company, onMove }: { company: CompanySummary; onMove: (stage: Stage) => void }) {
  const { attributes, listeners, setNodeRef, transform, isDragging } = useDraggable({ id: company.id });
  const style = transform ? { transform: `translate3d(${transform.x}px, ${transform.y}px, 0)` } : undefined;
  return (
    <div
      ref={setNodeRef}
      style={style}
      className={clsx(
        "rounded-xl border border-line bg-surface p-3 shadow-sm",
        isDragging && "relative z-10 rotate-1 shadow-lg ring-2 ring-accent",
      )}
    >
      <div
        {...listeners}
        {...attributes}
        aria-label={`Move ${company.name}`}
        className="cursor-grab active:cursor-grabbing"
      >
        <Link
          to={`/companies/${company.id}`}
          className="block text-[15px] font-semibold text-ink hover:underline"
          onPointerDown={(e) => e.stopPropagation()}
        >
          {company.name}
        </Link>
        {company.open_role && <p className="mt-0.5 text-[13px] leading-snug text-body">{company.open_role}</p>}
        <p className="mt-1.5 text-[13px] text-muted">
          {company.people_count} {company.people_count === 1 ? "person" : "people"}
          {company.posted && ` · posted ${formatDay(company.posted)}`}
        </p>
        {company.next_move && (
          <p className="mt-1 truncate text-[13px] text-muted">
            Next: {company.next_move.title} · {formatDay(company.next_move.due)}
          </p>
        )}
        {company.parked_reason && <p className="mt-1 text-[13px] text-muted">{company.parked_reason}</p>}
      </div>
      <label className="mt-2 flex items-center gap-2 text-[12px] text-muted">
        <span className="sr-only">Stage for {company.name}</span>
        <select
          className="w-full rounded-md border border-line bg-surface px-2 py-1 text-[12px] text-body"
          value={company.stage}
          onChange={(e) => onMove(e.target.value as Stage)}
        >
          {STAGES.map((s) => (
            <option key={s.key} value={s.key}>
              {s.label}
            </option>
          ))}
        </select>
      </label>
    </div>
  );
}

function Column({
  stage,
  companies,
  onMove,
}: {
  stage: Stage;
  companies: CompanySummary[];
  onMove: (id: string, s: Stage) => void;
}) {
  const { setNodeRef, isOver } = useDroppable({ id: stage });
  return (
    <section
      ref={setNodeRef}
      aria-label={stageLabel(stage)}
      className={clsx(
        "flex w-72 shrink-0 flex-col gap-2 rounded-card bg-[#EFEFF2] p-2.5 transition-colors",
        isOver && "bg-accent-tint ring-2 ring-accent",
      )}
    >
      <h2 className="flex items-center justify-between px-1 text-[13px] font-semibold text-body">
        {stageLabel(stage)}
        <span className="rounded-md bg-surface px-1.5 text-[12px] font-medium text-muted">{companies.length}</span>
      </h2>
      {companies.map((c) => (
        <CompanyCard key={c.id} company={c} onMove={(s) => onMove(c.id, s)} />
      ))}
      {companies.length === 0 && (
        <p className="rounded-xl border border-dashed border-[#C9C9D0] px-3 py-6 text-center text-[13px] text-muted">
          Drag a company here
        </p>
      )}
    </section>
  );
}

function AddCompany({ onDone }: { onDone: (id: string) => void }) {
  const add = useAddCompany();
  const [name, setName] = useState("");
  const [domain, setDomain] = useState("");
  const [role, setRole] = useState("");
  const [jobUrl, setJobUrl] = useState("");
  const submit = (e: FormEvent) => {
    e.preventDefault();
    add.mutate(
      { name, domain: domain || null, open_role: role || null, job_url: jobUrl || null },
      { onSuccess: (c) => onDone(c.id) },
    );
  };
  const field = "min-h-[38px] rounded-lg border border-line bg-surface px-3 text-sm";
  return (
    <Card className="p-4">
      <form onSubmit={submit} className="grid gap-3 sm:grid-cols-5" aria-label="Add a company">
        <input
          className={field}
          placeholder="Company name"
          aria-label="Company name"
          required
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
        <input
          className={field}
          placeholder="Domain"
          aria-label="Domain"
          value={domain}
          onChange={(e) => setDomain(e.target.value)}
        />
        <input
          className={field}
          placeholder="Open role"
          aria-label="Open role"
          value={role}
          onChange={(e) => setRole(e.target.value)}
        />
        <input
          className={field}
          placeholder="Posting link"
          aria-label="Posting link"
          type="url"
          value={jobUrl}
          onChange={(e) => setJobUrl(e.target.value)}
        />
        <Button type="submit" variant="primary" disabled={add.isPending}>
          Add company
        </Button>
      </form>
    </Card>
  );
}

export function PipelinePage() {
  const [q, setQ] = useState("");
  const [showPaused, setShowPaused] = useState(false);
  const [adding, setAdding] = useState(false);
  const navigate = useNavigate();
  const query = useDeferredValue(q.trim());
  const filters = { q: query || undefined };
  const { data, isPending, isError } = useCompanies(filters);
  const move = useMoveCompany(filters);
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
    useSensor(KeyboardSensor),
  );

  const onMove = (id: string, stage: Stage) => {
    const current = data?.items.find((c) => c.id === id);
    if (current && current.stage !== stage) move.mutate({ id, stage });
  };
  const onDragEnd = ({ active, over }: DragEndEvent) => {
    if (over) onMove(String(active.id), over.id as Stage);
  };
  const columns = showPaused ? [...BOARD, ...PAUSED] : BOARD;
  const paused = data?.items.filter((c) => PAUSED.includes(c.stage)).length ?? 0;

  return (
    <div className="flex flex-col gap-5">
      <PageHeader title="Pipeline">
        <label className="relative">
          <span className="sr-only">Search companies</span>
          <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-field" aria-hidden="true" />
          <input
            type="search"
            className="min-h-[38px] w-64 rounded-lg border border-line bg-surface pl-9 pr-3 text-sm"
            placeholder="Search companies or roles"
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
        </label>
        <Button variant="quiet" aria-pressed={showPaused} onClick={() => setShowPaused((v) => !v)}>
          {showPaused ? "Hide parked" : `Show parked (${paused})`}
        </Button>
        <Button variant="primary" onClick={() => setAdding((v) => !v)}>
          <Plus size={15} aria-hidden="true" />
          Add company
        </Button>
      </PageHeader>
      {adding && <AddCompany onDone={(id) => navigate(`/companies/${id}`)} />}
      {isPending ? (
        <p className="text-sm text-muted">Loading the board…</p>
      ) : isError ? (
        <EmptyState title="Couldn't load the board">Reload the page to try again.</EmptyState>
      ) : (
        <DndContext sensors={sensors} onDragEnd={onDragEnd}>
          <div className="-mx-4 flex gap-3 overflow-x-auto px-4 pb-4 md:-mx-8 md:px-8">
            {columns.map((stage) => (
              <Column
                key={stage}
                stage={stage}
                companies={data.items.filter((c) => c.stage === stage)}
                onMove={onMove}
              />
            ))}
          </div>
        </DndContext>
      )}
    </div>
  );
}
