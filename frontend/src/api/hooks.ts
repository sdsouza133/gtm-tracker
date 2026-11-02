import { keepPreviousData, useMutation, useQuery, useQueryClient, type QueryKey } from "@tanstack/react-query";

import { isoDay } from "@/lib/format";

import { ApiError, api, unwrap } from "./client";
import type { components } from "./schema";

export type S = components["schemas"];
export type Stage = S["CompanySummary"]["stage"];
export type Move = S["MoveOut"];
export type MoveCard = S["MoveCard"];
export type Person = S["PersonOut"];
export type CompanySummary = S["CompanySummary"];
export type CompanyDetail = S["CompanyDetail"];
export type Step = S["StepTick"]["step"];
export type PersonStatus = S["PersonOut"]["status"];
export type RoleInHire = S["PersonOut"]["role_in_hire"];
export type Sureness = NonNullable<S["PersonOut"]["sureness"]>;
export type MoveType = S["MoveOut"]["type"];

export const keys = {
  today: ["today"] as const,
  stats: ["stats"] as const,
  companies: (filters: object) => ["companies", filters] as const,
  company: (id: string) => ["company", id] as const,
  people: (filters: object) => ["people", filters] as const,
  plan: ["plan"] as const,
  activity: ["activity"] as const,
  settings: ["settings"] as const,
};

/** What a change to moves, people or companies can affect. Refetched after every change (only the ones on screen). */
const AFFECTED: QueryKey[] = [keys.today, keys.stats, ["companies"], ["company"], ["people"], keys.plan, keys.activity];

function useChange<TVars, TData>(fn: (vars: TVars) => Promise<TData>) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSettled: () => Promise.all(AFFECTED.map((queryKey) => client.invalidateQueries({ queryKey }))),
  });
}

// ----------------------------------------------------------------------------- reads

/** The day's list; `showAll` includes the companies held back by the daily limit. */
export function useToday(showAll = false) {
  return useQuery({
    queryKey: [...keys.today, { showAll }],
    queryFn: async () => unwrap(await api.GET("/api/today", { params: { query: { show_all: showAll } } })),
  });
}

/** The server's "today" (the configured time zone's calendar day), or the browser's until the server answers. */
export function useServerToday(): string {
  return useToday().data?.today ?? isoDay(new Date());
}

export function useStats() {
  return useQuery({ queryKey: keys.stats, queryFn: async () => unwrap(await api.GET("/api/stats")) });
}

export type CompanyFilters = { q?: string; stage?: Stage[] };

export function useCompanies(filters: CompanyFilters) {
  return useQuery({
    queryKey: keys.companies(filters),
    queryFn: async () => unwrap(await api.GET("/api/companies", { params: { query: { ...filters, limit: 500 } } })),
    placeholderData: keepPreviousData,
  });
}

export function useCompany(id: string) {
  return useQuery({
    queryKey: keys.company(id),
    queryFn: async () => unwrap(await api.GET("/api/companies/{company_id}", { params: { path: { company_id: id } } })),
  });
}

export type PeopleFilters = {
  q?: string;
  status?: PersonStatus;
  role?: RoleInHire;
  sureness?: Sureness;
  offset?: number;
};

export function usePeople(filters: PeopleFilters) {
  return useQuery({
    queryKey: keys.people(filters),
    queryFn: async () => unwrap(await api.GET("/api/people", { params: { query: { ...filters, limit: 50 } } })),
    placeholderData: keepPreviousData,
  });
}

export function usePlan() {
  return useQuery({ queryKey: keys.plan, queryFn: async () => unwrap(await api.GET("/api/plan")) });
}

export function useActivity(before?: number) {
  return useQuery({
    queryKey: [...keys.activity, before ?? 0],
    queryFn: async () => unwrap(await api.GET("/api/activity", { params: { query: { before, limit: 50 } } })),
  });
}

export function useSettings() {
  return useQuery({ queryKey: keys.settings, queryFn: async () => unwrap(await api.GET("/api/settings")) });
}

// ----------------------------------------------------------------------------- changes

export function useTickStep() {
  return useChange(async ({ id, step, value }: { id: string; step: Step; value?: "today" | "na" | null }) =>
    unwrap(
      await api.POST("/api/moves/{move_id}/steps", {
        params: { path: { move_id: id } },
        body: { step, value: value === undefined ? "today" : value },
      }),
    ),
  );
}

export function useUpdateMove() {
  return useChange(async ({ id, ...body }: { id: string } & S["MovePatch"]) =>
    unwrap(await api.PATCH("/api/moves/{move_id}", { params: { path: { move_id: id } }, body })),
  );
}

export function useAddMove() {
  return useChange(async (body: S["MoveCreate"]) => unwrap(await api.POST("/api/moves", { body })));
}

export function useDeleteMove() {
  return useChange(async (id: string) => {
    const { response } = await api.DELETE("/api/moves/{move_id}", { params: { path: { move_id: id } } });
    if (!response.ok) throw new ApiError(response.status, "Couldn't delete it. Try again.");
  });
}

export function usePull() {
  return useChange(async (n: number) => unwrap(await api.POST("/api/moves/pull", { body: { n } })));
}

export function useReply() {
  return useChange(async ({ id, text }: { id: string; text: string }) =>
    unwrap(await api.POST("/api/people/{person_id}/reply", { params: { path: { person_id: id } }, body: { text } })),
  );
}

/** Finding work emails with Apollo. It runs on its own in the background, so a 409 ("not set up yet") stays quiet;
 * anything else says what went wrong. */
export const NOT_SET_UP = 409;

/** Whether a lookup failed for a reason worth showing (not just "Apollo isn't switched on yet"). */
export function lookupFailed(error: Error | null): boolean {
  return error !== null && !(error instanceof ApiError && error.status === NOT_SET_UP);
}

function useEnrich<TVars>(fn: (vars: TVars) => Promise<S["EnrichOut"]>) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: fn,
    meta: { quiet: NOT_SET_UP },
    // refetch even when no one was looked up: "what they do" may have been filled in
    onSuccess: () => Promise.all(AFFECTED.map((queryKey) => client.invalidateQueries({ queryKey }))),
  });
}

export function useEnrichCompany() {
  return useEnrich(async (id: string) =>
    unwrap(await api.POST("/api/companies/{company_id}/enrich", { params: { path: { company_id: id } } })),
  );
}

export function useEnrichToday() {
  return useEnrich<undefined>(async () => unwrap(await api.POST("/api/enrich/today")));
}

export function useUpdatePerson() {
  return useChange(async ({ id, ...body }: { id: string } & S["PersonPatch"]) =>
    unwrap(await api.PATCH("/api/people/{person_id}", { params: { path: { person_id: id } }, body })),
  );
}

export function useAddPerson() {
  return useChange(async (body: S["PersonCreate"]) => unwrap(await api.POST("/api/people", { body })));
}

export function useAddCompany() {
  return useChange(async (body: S["CompanyCreate"]) => unwrap(await api.POST("/api/companies", { body })));
}

export function useUpdateCompany() {
  return useChange(async ({ id, ...body }: { id: string } & S["CompanyPatch"]) =>
    unwrap(await api.PATCH("/api/companies/{company_id}", { params: { path: { company_id: id } }, body })),
  );
}

/** Moving a company to another stage shows at once on the board, and rolls back if the server says no. */
export function useMoveCompany(filters: CompanyFilters) {
  const client = useQueryClient();
  const key = keys.companies(filters);
  return useMutation({
    mutationFn: async ({ id, stage }: { id: string; stage: Stage }) =>
      unwrap(await api.PATCH("/api/companies/{company_id}", { params: { path: { company_id: id } }, body: { stage } })),
    onMutate: async ({ id, stage }) => {
      await client.cancelQueries({ queryKey: key });
      const before = client.getQueryData<S["Page_CompanySummary_"]>(key);
      if (before) {
        client.setQueryData(key, {
          ...before,
          items: before.items.map((c) => (c.id === id ? { ...c, stage } : c)),
        });
      }
      return { before };
    },
    onError: (_error, _vars, context) => {
      if (context?.before) client.setQueryData(key, context.before);
    },
    onSettled: () => Promise.all(AFFECTED.map((queryKey) => client.invalidateQueries({ queryKey }))),
  });
}

export function usePromote() {
  return useChange(async ({ id, wave }: { id: string; wave: string }) =>
    unwrap(
      await api.POST("/api/companies/{company_id}/promote", { params: { path: { company_id: id } }, body: { wave } }),
    ),
  );
}

export function useAddNote() {
  return useChange(async (body: S["NoteCreate"]) => unwrap(await api.POST("/api/activity", { body })));
}

export function useUpdateSettings() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (body: S["SettingsOut"]) => unwrap(await api.PATCH("/api/settings", { body })),
    onSuccess: (data) => {
      client.setQueryData(keys.settings, data);
      // the Fractional board shows today's goal, which lives in settings
      return Promise.all([
        client.invalidateQueries({ queryKey: keys.stats }),
        client.invalidateQueries({ queryKey: fxKeys.board }),
      ]);
    },
  });
}

// ----------------------------------------------------------------------------- fractional

export type ProspectCard = S["ProspectCard"];
export type ProspectDetail = S["ProspectDetail"];
export type FxShow = "all" | "untouched" | "in_play" | "closed";

export const fxKeys = {
  all: ["fx"] as const,
  board: ["fx", "board"] as const,
  pipeline: ["fx", "pipeline"] as const,
  list: (filters: object) => ["fx", "list", filters] as const,
  one: (id: string) => ["fx", "one", id] as const,
};

export function useFxBoard() {
  return useQuery({ queryKey: fxKeys.board, queryFn: async () => unwrap(await api.GET("/api/fx/board")) });
}

export function useFxPipeline() {
  return useQuery({ queryKey: fxKeys.pipeline, queryFn: async () => unwrap(await api.GET("/api/fx/pipeline")) });
}

export function useFxProspects(filters: { q?: string; show: FxShow; offset: number }) {
  return useQuery({
    queryKey: fxKeys.list(filters),
    queryFn: async () => unwrap(await api.GET("/api/fx/prospects", { params: { query: { ...filters, limit: 100 } } })),
    placeholderData: keepPreviousData,
  });
}

export function useFxProspect(id: string | null) {
  return useQuery({
    queryKey: fxKeys.one(id ?? ""),
    queryFn: async () =>
      unwrap(await api.GET("/api/fx/prospects/{prospect_id}", { params: { path: { prospect_id: id ?? "" } } })),
    enabled: id !== null,
  });
}

/** Changes to a prospect. Text fields (notes, draft) update the open prospect in place without refetching lists. */
export function useUpdateProspect() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async ({ id, ...body }: { id: string } & S["ProspectPatch"]) =>
      unwrap(await api.PATCH("/api/fx/prospects/{prospect_id}", { params: { path: { prospect_id: id } }, body })),
    onSuccess: (data, vars) => {
      client.setQueryData(fxKeys.one(data.id), data);
      const textOnly = Object.keys(vars).every((k) => k === "id" || k === "my_notes" || k === "draft");
      if (!textOnly) return client.invalidateQueries({ queryKey: fxKeys.all, refetchType: "active" });
      return undefined;
    },
  });
}

// ----------------------------------------------------------------------------- radar

export type RadarState = S["RadarOut"];
export type RadarItem = S["RadarItemOut"];
const RADAR = ["radar"] as const;
const RUNNING_POLL_MS = 4000;

export function useRadar() {
  return useQuery({
    queryKey: RADAR,
    queryFn: async () => unwrap(await api.GET("/api/radar")),
    // while a run is going, follow its progress
    refetchInterval: (query) => (query.state.data?.status["running"] ? RUNNING_POLL_MS : false),
  });
}

function useRadarChange<TVars, TData>(fn: (vars: TVars) => Promise<TData>) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSettled: () => Promise.all([RADAR, ...AFFECTED].map((queryKey) => client.invalidateQueries({ queryKey }))),
  });
}

export function useRunRadar() {
  return useRadarChange(async () => unwrap(await api.POST("/api/radar/run")));
}

export function useAddRadarItem() {
  return useRadarChange(async (id: string) =>
    unwrap(await api.POST("/api/radar/items/{item_id}/add", { params: { path: { item_id: id } } })),
  );
}

export function useDismissRadarItem() {
  return useRadarChange(async (id: string) =>
    unwrap(await api.POST("/api/radar/items/{item_id}/dismiss", { params: { path: { item_id: id } } })),
  );
}

export function useUpdateRadarConfig() {
  return useRadarChange(async (body: S["RadarConfigPatch"]) => unwrap(await api.PATCH("/api/radar/config", { body })));
}

// ----------------------------------------------------------------------------- lead magnets

export type Magnet = S["MagnetOut"];
export type MagnetMode = S["MagnetCreate"]["mode"];
export type PublicMagnet = S["PublicMagnet"];
export type PublicLead = S["PublicLead"];
const BUILDING_POLL_MS = 3000;
const magnetKeys = {
  forCompany: (companyId: string) => ["magnets", companyId] as const,
  report: (id: string, token: string) => ["magnet-report", id, token] as const,
};

export function useMagnets(companyId: string) {
  return useQuery({
    queryKey: magnetKeys.forCompany(companyId),
    queryFn: async () =>
      unwrap(await api.GET("/api/companies/{company_id}/magnets", { params: { path: { company_id: companyId } } })),
    // while one builds, follow its steps
    refetchInterval: (query) => (query.state.data?.some((m) => m.status === "running") ? BUILDING_POLL_MS : false),
  });
}

export function useBuildMagnet(companyId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (body: { mode: MagnetMode; website?: string; competitors?: string[] }) =>
      unwrap(
        await api.POST("/api/companies/{company_id}/magnets", {
          params: { path: { company_id: companyId } },
          body,
        }),
      ),
    onSettled: () => client.invalidateQueries({ queryKey: magnetKeys.forCompany(companyId) }),
  });
}

export function useDeleteMagnet(companyId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (id: string) => {
      const result = await api.DELETE("/api/magnets/{magnet_id}", { params: { path: { magnet_id: id } } });
      if (!result.response.ok) unwrap(result);
    },
    onSettled: () => client.invalidateQueries({ queryKey: magnetKeys.forCompany(companyId) }),
  });
}

/** A finished report, by its private link. Works without signing in. */
export function usePublicMagnet(id: string, token: string) {
  return useQuery({
    queryKey: magnetKeys.report(id, token),
    queryFn: async () =>
      unwrap(await api.GET("/api/public/magnets/{magnet_id}/{token}", { params: { path: { magnet_id: id, token } } })),
    staleTime: Infinity, // each load counts as a view; don't refetch on focus
  });
}

// ----------------------------------------------------------------------------- the events tool

export type EventsHome = S["EventsHome"];
export type EventRun = S["EventRunOut"];
export type EventRunSummary = S["EventRunSummary"];
export type EventPlan = S["EventPlan"];
export type PlanEvent = S["PlanEvent"];
export type Icp = S["Icp"];
export type EventLead = S["EventLeadOut"];

const eventKeys = {
  home: (companyId?: string) => ["events", companyId ?? "all"] as const,
  run: (id: string) => ["event-run", id] as const,
  leads: (id: string) => ["event-leads", id] as const,
};
const POLL_MS = 3000;

/** The tool's state, today's spend and the latest runs (for one company, given its id). */
export function useEventsHome(companyId?: string) {
  return useQuery({
    queryKey: eventKeys.home(companyId),
    queryFn: async () =>
      unwrap(await api.GET("/api/events", { params: { query: companyId ? { company_id: companyId } : {} } })),
    refetchInterval: (query) => (query.state.data?.runs.some((r) => WORKING.has(r.status)) ? POLL_MS : false),
  });
}

/** What a run's page shows while the worker is on it; it checks back every few seconds. */
export const WORKING = new Set(["analyzing", "collecting", "waiting_for_budget", "qualifying", "enriching"]);

export function useEventRun(id: string) {
  return useQuery({
    queryKey: eventKeys.run(id),
    queryFn: async () => unwrap(await api.GET("/api/events/runs/{run_id}", { params: { path: { run_id: id } } })),
    refetchInterval: (query) => (query.state.data?.working ? POLL_MS : false),
  });
}

export function useEventLeads(id: string, ready: boolean) {
  return useQuery({
    queryKey: eventKeys.leads(id),
    queryFn: async () => unwrap(await api.GET("/api/events/runs/{run_id}/leads", { params: { path: { run_id: id } } })),
    enabled: ready,
  });
}

function useEventsChange<TVars>(fn: (vars: TVars) => Promise<EventRun>) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: (run) => client.setQueryData(eventKeys.run(run.id), run),
    onSettled: () => client.invalidateQueries({ queryKey: ["events"] }),
  });
}

export function useStartEventRun() {
  return useEventsChange(async (body: { website: string; company_id?: string }) =>
    unwrap(await api.POST("/api/events/runs", { body })),
  );
}

export function useSavePlan(id: string) {
  return useEventsChange(async (body: S["EventPlanSave"]) =>
    unwrap(await api.PUT("/api/events/runs/{run_id}/plan", { params: { path: { run_id: id } }, body })),
  );
}

export function useAddEvent(id: string) {
  return useEventsChange(async (body: S["EventAdd"]) =>
    unwrap(await api.POST("/api/events/runs/{run_id}/events", { params: { path: { run_id: id } }, body })),
  );
}

export function useCancelEventRun(id: string) {
  return useEventsChange(async () =>
    unwrap(await api.POST("/api/events/runs/{run_id}/cancel", { params: { path: { run_id: id } } })),
  );
}

export function useHoldNewRuns() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (paused: boolean) => {
      const result = await api.PUT("/api/events/new-runs", { body: { paused } });
      if (!result.response.ok) unwrap(result);
    },
    onSettled: () => client.invalidateQueries({ queryKey: ["events"] }),
  });
}
