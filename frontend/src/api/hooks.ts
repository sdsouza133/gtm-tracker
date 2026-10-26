import { keepPreviousData, useMutation, useQuery, useQueryClient, type QueryKey } from "@tanstack/react-query";

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

export function useToday() {
  return useQuery({ queryKey: keys.today, queryFn: async () => unwrap(await api.GET("/api/today")) });
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
      return client.invalidateQueries({ queryKey: keys.stats });
    },
  });
}
