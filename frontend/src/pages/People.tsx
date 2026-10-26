import { Search } from "lucide-react";
import { useDeferredValue, useState } from "react";
import { Link } from "react-router-dom";

import { type PersonStatus, type RoleInHire, type Sureness, usePeople } from "@/api/hooks";
import { Button, Card, Chip, EmptyState, PageHeader } from "@/components/ui";
import { LEADERS, ROLE_LABEL, STATUS_LABEL, SURE_LABEL } from "@/lib/format";

const PAGE = 50;
const select = "min-h-[38px] rounded-lg border border-line bg-surface px-3 text-sm";

export function PeoplePage() {
  const [q, setQ] = useState("");
  const [status, setStatus] = useState<PersonStatus | "">("");
  const [role, setRole] = useState<RoleInHire | "">("");
  const [sureness, setSureness] = useState<Sureness | "">("");
  const [offset, setOffset] = useState(0);
  const query = useDeferredValue(q.trim());
  const { data, isPending, isError } = usePeople({
    q: query || undefined,
    status: status || undefined,
    role: role || undefined,
    sureness: sureness || undefined,
    offset,
  });
  const reset =
    <T,>(set: (v: T) => void) =>
    (v: T) => {
      set(v);
      setOffset(0);
    };

  return (
    <div className="flex max-w-6xl flex-col gap-5">
      <PageHeader title="People" eyebrow={data ? `${data.total} people` : undefined} />
      <div className="flex flex-wrap gap-2">
        <label className="relative">
          <span className="sr-only">Search people</span>
          <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-field" aria-hidden="true" />
          <input
            type="search"
            className="min-h-[38px] w-64 rounded-lg border border-line bg-surface pl-9 pr-3 text-sm"
            placeholder="Name or title"
            value={q}
            onChange={(e) => reset(setQ)(e.target.value)}
          />
        </label>
        <select
          className={select}
          aria-label="Status"
          value={status}
          onChange={(e) => reset(setStatus)(e.target.value as PersonStatus | "")}
        >
          <option value="">Any status</option>
          {Object.entries(STATUS_LABEL).map(([k, v]) => (
            <option key={k} value={k}>
              {v}
            </option>
          ))}
        </select>
        <select
          className={select}
          aria-label="Part in the hire"
          value={role}
          onChange={(e) => reset(setRole)(e.target.value as RoleInHire | "")}
        >
          <option value="">Any part</option>
          {Object.entries(ROLE_LABEL).map(([k, v]) => (
            <option key={k} value={k}>
              {v}
            </option>
          ))}
        </select>
        <select
          className={select}
          aria-label="How sure"
          value={sureness}
          onChange={(e) => reset(setSureness)(e.target.value as Sureness | "")}
        >
          <option value="">Any certainty</option>
          {Object.entries(SURE_LABEL).map(([k, v]) => (
            <option key={k} value={k}>
              {v}
            </option>
          ))}
        </select>
      </div>
      {isPending ? (
        <p className="text-sm text-muted">Loading people…</p>
      ) : isError ? (
        <EmptyState title="Couldn't load people">Reload the page to try again.</EmptyState>
      ) : data.items.length === 0 ? (
        <EmptyState title="No one matches">Try fewer filters.</EmptyState>
      ) : (
        <Card className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-line text-[12px] font-medium text-muted">
              <tr>
                <th scope="col" className="px-4 py-2.5 font-medium">
                  Name
                </th>
                <th scope="col" className="px-4 py-2.5 font-medium">
                  Part in the hire
                </th>
                <th scope="col" className="px-4 py-2.5 font-medium">
                  Status
                </th>
                <th scope="col" className="px-4 py-2.5 font-medium">
                  Where
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line-soft">
              {data.items.map((p) => (
                <tr key={p.id} className={p.left ? "opacity-60" : undefined}>
                  <td className="px-4 py-3">
                    <Link to={`/companies/${p.company_id}`} className="font-semibold text-ink hover:underline">
                      {p.name}
                    </Link>
                    <p className="text-[13px] text-muted">{p.title}</p>
                  </td>
                  <td className="px-4 py-3">
                    <Chip tone={LEADERS.has(p.role_in_hire) ? "accent" : "neutral"}>{ROLE_LABEL[p.role_in_hire]}</Chip>
                    {p.sureness && <span className="ml-2 text-[13px] text-muted">{SURE_LABEL[p.sureness]}</span>}
                  </td>
                  <td className="px-4 py-3">
                    {p.left ? (
                      <Chip tone="bad">Left</Chip>
                    ) : p.status === "replied" ? (
                      <Chip tone="good">Replied</Chip>
                    ) : (
                      STATUS_LABEL[p.status]
                    )}
                  </td>
                  <td className="px-4 py-3 text-muted">{p.location}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}
      {data && data.total > PAGE && (
        <div className="flex items-center justify-between text-sm text-muted">
          <span>
            {offset + 1}–{Math.min(offset + PAGE, data.total)} of {data.total}
          </span>
          <div className="flex gap-2">
            <Button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>
              Previous
            </Button>
            <Button disabled={offset + PAGE >= data.total} onClick={() => setOffset(offset + PAGE)}>
              Next
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
