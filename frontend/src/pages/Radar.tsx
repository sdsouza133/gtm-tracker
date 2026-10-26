import { clsx } from "clsx";
import { ExternalLink, Plus, RefreshCw, X } from "lucide-react";
import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";

import {
  type RadarItem,
  type RadarState,
  useAddRadarItem,
  useDismissRadarItem,
  useRadar,
  useRunRadar,
  useUpdateRadarConfig,
} from "@/api/hooks";
import { notify } from "@/components/Toast";
import { Button, Card, Chip, EmptyState, PageHeader } from "@/components/ui";
import { formatDateTimeDay, formatDay, formatTime } from "@/lib/format";
import { safeUrl } from "@/lib/safe";

const FIT_LABEL: Record<number, string> = { 3: "The role", 2: "Next door", 1: "Worth a look" };
const field = "min-h-[38px] rounded-lg border border-line bg-surface px-3 text-sm";

function Status({ data }: { data: RadarState }) {
  const run = useRunRadar();
  const s = data.status as {
    running?: boolean;
    step?: string;
    last_run_at?: string;
    error?: string;
    summary?: Record<string, number>;
  };
  const sm = s.summary ?? {};
  return (
    <Card className="flex flex-wrap items-center justify-between gap-4 p-4">
      <div className="min-w-0">
        <p className="text-[15px] font-semibold">
          {s.running ? `Running: ${s.step || "starting"}…` : s.last_run_at ? "Last run" : "Not run yet"}
          {!s.running && s.last_run_at && (
            <span className="font-normal text-muted">
              {" "}
              {formatDateTimeDay(s.last_run_at)} at {formatTime(s.last_run_at)}
            </span>
          )}
        </p>
        {!s.running && s.last_run_at && (
          <p className="text-[13px] text-muted">
            {(sm["tracked_new"] ?? 0) + (sm["linkedin_tracked"] ?? 0)} new at your companies · {sm["inbox_new"] ?? 0}{" "}
            new in the inbox · {sm["boards_checked"] ?? 0} job boards checked
            {sm["spent_usd"] ? ` · $${sm["spent_usd"].toFixed(2)} on searches` : ""}
          </p>
        )}
        {s.error && <p className="mt-1 text-[13px] text-bad">{s.error}</p>}
        {!data.apify && (
          <p className="mt-1 text-[13px] text-muted">
            Job boards are checked for free. LinkedIn and hiring-post searches need an Apify token on the server.
          </p>
        )}
      </div>
      <Button
        variant="primary"
        disabled={run.isPending || !!s.running}
        onClick={() =>
          run.mutate(undefined, { onSuccess: () => notify("Radar started. This page updates as it runs.") })
        }
      >
        <RefreshCw size={14} aria-hidden="true" className={clsx(s.running && "animate-spin")} />
        Check now
      </Button>
    </Card>
  );
}

function InboxRow({ item }: { item: RadarItem }) {
  const add = useAddRadarItem();
  const dismiss = useDismissRadarItem();
  const navigate = useNavigate();
  const busy = add.isPending || dismiss.isPending;
  return (
    <article className="flex flex-col gap-2 px-4 py-3.5 sm:flex-row sm:items-start">
      <div className="min-w-0 flex-1">
        <p className="text-[15px]">
          {safeUrl(item.url) ? (
            <a
              href={safeUrl(item.url)}
              target="_blank"
              rel="noreferrer"
              className="font-semibold text-ink hover:underline"
            >
              {item.title}
            </a>
          ) : (
            <span className="font-semibold text-ink">{item.title}</span>
          )}
          <span className="text-muted"> · {item.company}</span>
        </p>
        <div className="mt-1 flex flex-wrap items-center gap-1.5 text-[13px] text-muted">
          <Chip tone={item.fit === 3 ? "accent" : "neutral"}>{FIT_LABEL[item.fit] ?? `Fit ${item.fit}`}</Chip>
          {item.flags.includes("canada") && <Chip tone="warm">Canada</Chip>}
          {item.flags.includes("remote") && <Chip tone="good">Remote</Chip>}
          {item.flags.includes("us_only") && <Chip tone="bad">US work authorization</Chip>}
          {item.on_bench && <Chip>On your bench</Chip>}
          {item.location && <span>{item.location}</span>}
          {item.salary && <span>· {item.salary}</span>}
          {item.posted && <span>· posted {formatDay(item.posted)}</span>}
          <span>· {item.source}</span>
        </div>
        {item.snippet && <p className="mt-1.5 line-clamp-2 text-[13px] text-body">{item.snippet}</p>}
      </div>
      <div className="flex shrink-0 gap-2">
        <Button
          variant="primary"
          disabled={busy}
          onClick={() =>
            add.mutate(item.id, {
              onSuccess: (r) => {
                notify(`${item.company} added with an Apply move for today`);
                navigate(`/companies/${r.company_id}`);
              },
            })
          }
        >
          <Plus size={14} aria-hidden="true" /> Add
        </Button>
        <Button
          variant="quiet"
          disabled={busy}
          aria-label={`Dismiss ${item.title} at ${item.company}`}
          onClick={() => dismiss.mutate(item.id)}
        >
          <X size={14} aria-hidden="true" />
        </Button>
      </div>
    </article>
  );
}

function Settings({ data }: { data: RadarState }) {
  const save = useUpdateRadarConfig();
  const c = data.config;
  const [keywords, setKeywords] = useState(c.keywords.join(", "));
  const [locations, setLocations] = useState(c.locations.join(", "));
  const [hour, setHour] = useState(String(c.hour)); // strings, so a cleared field stays empty and `required` stops the save
  const [minUsd, setMinUsd] = useState(String(c.min_usd));
  const [minCad, setMinCad] = useState(String(c.min_cad));
  const [flags, setFlags] = useState({
    core_only: c.core_only,
    toronto_ok: c.toronto_ok,
    ats_search: c.ats_search,
    post_search: c.post_search,
  });
  const list = (text: string) =>
    text
      .split(",")
      .map((x) => x.trim())
      .filter(Boolean);
  const submit = (e: FormEvent) => {
    e.preventDefault();
    save.mutate(
      {
        keywords: list(keywords),
        locations: list(locations),
        hour: Number(hour),
        min_usd: Number(minUsd),
        min_cad: Number(minCad),
        ...flags,
      },
      { onSuccess: () => notify("Radar settings saved") },
    );
  };
  const toggles: [keyof typeof flags, string][] = [
    ["core_only", "Only GTM engineering roles"],
    ["toronto_ok", "Only roles I can do from Toronto"],
    ["ats_search", "Search company job boards through Google"],
    ["post_search", "Search LinkedIn hiring posts"],
  ];
  return (
    <form onSubmit={submit} className="grid gap-3 p-4 sm:grid-cols-2" aria-label="Radar settings">
      <label className="flex flex-col gap-1 text-[13px] font-medium text-muted sm:col-span-2">
        Job titles to search (comma-separated)
        <input className={field} value={keywords} onChange={(e) => setKeywords(e.target.value)} />
      </label>
      <label className="flex flex-col gap-1 text-[13px] font-medium text-muted">
        Locations
        <input className={field} value={locations} onChange={(e) => setLocations(e.target.value)} />
      </label>
      <label className="flex flex-col gap-1 text-[13px] font-medium text-muted">
        Morning run at (hour, 0–23)
        <input
          className={field}
          type="number"
          required
          min={0}
          max={23}
          value={hour}
          onChange={(e) => setHour(e.target.value)}
        />
      </label>
      <label className="flex flex-col gap-1 text-[13px] font-medium text-muted">
        Lowest pay, USD (top of the range)
        <input
          className={field}
          type="number"
          required
          min={0}
          step={1000}
          value={minUsd}
          onChange={(e) => setMinUsd(e.target.value)}
        />
      </label>
      <label className="flex flex-col gap-1 text-[13px] font-medium text-muted">
        Lowest pay, CAD
        <input
          className={field}
          type="number"
          required
          min={0}
          step={1000}
          value={minCad}
          onChange={(e) => setMinCad(e.target.value)}
        />
      </label>
      {toggles.map(([key, label]) => (
        <label key={key} className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={flags[key]}
            onChange={(e) => setFlags({ ...flags, [key]: e.target.checked })}
          />
          {label}
        </label>
      ))}
      <div className="sm:col-span-2">
        <Button type="submit" variant="primary" disabled={save.isPending}>
          Save settings
        </Button>
      </div>
    </form>
  );
}

export function RadarPage() {
  const { data, isPending, isError } = useRadar();
  const [showSettings, setShowSettings] = useState(false);
  if (isPending) return <p className="text-sm text-muted">Loading the radar…</p>;
  if (isError) return <EmptyState title="Couldn't load the radar">Reload the page to try again.</EmptyState>;
  return (
    <div className="flex max-w-6xl flex-col gap-6">
      <PageHeader title="Radar" eyebrow="New GTM roles, every morning">
        <Button variant="quiet" aria-expanded={showSettings} onClick={() => setShowSettings((v) => !v)}>
          {showSettings ? "Hide settings" : "Settings"}
        </Button>
      </PageHeader>
      <Status data={data} />
      {showSettings && (
        <Card>
          <Settings data={data} />
        </Card>
      )}
      <section aria-labelledby="inbox" className="flex flex-col gap-2">
        <div className="flex items-baseline justify-between">
          <h2 id="inbox" className="text-[15px] font-semibold">
            Inbox
          </h2>
          <span className="text-[13px] text-muted">{data.items.length}</span>
        </div>
        <p className="-mt-1 text-[13px] text-muted">
          Roles at companies you don't track yet. New roles at your companies go straight to Today as Apply moves.
        </p>
        {data.items.length ? (
          <Card className="divide-y divide-line-soft">
            {data.items.map((item) => (
              <InboxRow key={item.id} item={item} />
            ))}
          </Card>
        ) : (
          <EmptyState title="Inbox is clear">New roles that fit show up here after each run.</EmptyState>
        )}
      </section>
      <section aria-labelledby="posts" className="flex flex-col gap-2">
        <div className="flex items-baseline justify-between">
          <h2 id="posts" className="text-[15px] font-semibold">
            Hiring posts
          </h2>
          <span className="text-[13px] text-muted">{data.posts.length}</span>
        </div>
        <p className="-mt-1 text-[13px] text-muted">
          People saying on LinkedIn that they're hiring a GTM engineer. The poster is often the hiring manager.
        </p>
        {data.posts.length ? (
          <Card className="divide-y divide-line-soft">
            {data.posts.map((p) => (
              <article key={p.id} className="flex flex-col gap-1 px-4 py-3">
                <p className="text-sm">
                  <a
                    href={safeUrl(p.author_url) ?? safeUrl(p.url)}
                    target="_blank"
                    rel="noreferrer"
                    className="font-semibold hover:underline"
                  >
                    {p.author || "Someone"}
                  </a>
                  {p.headline && <span className="text-muted"> · {p.headline}</span>}
                  {p.recruiter && (
                    <span className="ml-2">
                      <Chip>Recruiter</Chip>
                    </span>
                  )}
                </p>
                <p className="line-clamp-3 text-[13px] text-body">{p.text}</p>
                {safeUrl(p.url) && (
                  <a
                    href={safeUrl(p.url)}
                    target="_blank"
                    rel="noreferrer"
                    className="inline-flex w-fit items-center gap-1 text-[13px] text-accent hover:underline"
                  >
                    Open the post <ExternalLink size={12} aria-hidden="true" />
                  </a>
                )}
              </article>
            ))}
          </Card>
        ) : (
          <EmptyState title="No hiring posts yet" />
        )}
      </section>
    </div>
  );
}
