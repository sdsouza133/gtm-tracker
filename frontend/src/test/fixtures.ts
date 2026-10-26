import type { CompanySummary, MoveCard, Person, S } from "@/api/hooks";

/** Made-up records for tests. */
export const TODAY = "2026-10-26";

export function company(over: Partial<S["CompanyBrief"]> = {}): S["CompanyBrief"] {
  return {
    id: "c1",
    name: "Northwind Labs",
    domain: "northwind.example",
    stage: "contacted",
    open_role: "GTM Engineer",
    job_url: null,
    posted: "2026-10-23",
    region: "Canada",
    cant_apply: false,
    ...over,
  };
}

export function person(over: Partial<Person> = {}): Person {
  return {
    id: "p1",
    company_id: "c1",
    name: "Priya Example",
    title: "GTM Program Manager",
    linkedin: "https://www.linkedin.com/in/priya-example",
    email: "priya@northwind.example",
    location: "Toronto",
    status: "none",
    role_in_hire: "hiring manager",
    sureness: "likely",
    left: false,
    why: "Runs the team",
    notes: "",
    emailed_at: null,
    ab_variant: null,
    drafts: [{ type: "email_day0", subject: "Hello", body: "A short note" }],
    details: {},
    ...over,
  };
}

export function move(over: Partial<MoveCard> = {}): MoveCard {
  return {
    id: "m1",
    company_id: "c1",
    person_id: "p1",
    type: "reach",
    title: "Reach out to Priya Example",
    due: TODAY,
    status: "open",
    notes: "",
    url: null,
    skip_reason: null,
    done_at: null,
    sequence: { day0: TODAY, steps: {}, next: "email+request", snooze: null, closed: null, replied: null },
    company: company(),
    person: person(),
    ...over,
  };
}

export function summary(over: Partial<CompanySummary> = {}): CompanySummary {
  return {
    ...company(),
    wave: "1",
    rank: 1,
    score: 4.2,
    hq: "Toronto",
    employees: "300",
    parked_why: null,
    parked_reason: null,
    people_count: 3,
    next_move: null,
    ...over,
  };
}

export const SIGNED_IN = { "GET /api/auth/me": { body: { signed_in: true, csrf: "token" } } };

export const STATS: S["StatsOut"] = {
  xp: 52,
  level: 2,
  level_title: "Sending",
  level_floor_xp: 40,
  next_level_xp: 160,
  streak: 4,
  best_streak: 9,
  streak_min: 3,
  today_moves: 2,
  recent: [],
  funnel: { contacted: 5, replied: 2, call_booked: 1, offer: 0 },
  in_play: 12,
  days_left: 40,
};
