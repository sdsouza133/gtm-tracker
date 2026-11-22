import type {
  Champion,
  ChampionsReport,
  ChampionsSummary,
  CompanySummary,
  Magnet,
  MoveCard,
  Person,
  S,
} from "@/api/hooks";

/** Made-up records for tests. */
export const TODAY = "2026-10-26";

export function company(over: Partial<S["CompanyBrief"]> = {}): S["CompanyBrief"] {
  return {
    id: "c1",
    name: "Northwind Labs",
    domain: "northwind.example",
    stage: "contacted",
    score: 4.2,
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

export const SIGNED_IN = {
  "GET /api/auth/me": { body: { signed_in: true, csrf: "token", password_login: true } },
  // Today looks emails up in the background; by default Apollo isn't switched on, which stays quiet
  "POST /api/enrich/today": { status: 409, body: { detail: "Turn on sign-in before finding emails." } },
};

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

/** A made-up champion: ran CX at a customer, now at a new company in the ICP. */
export function champion(over: Partial<Champion> = {}): Champion {
  return {
    name: "Dana Example",
    linkedin: "https://www.linkedin.com/in/dana-example",
    location: "Austin, Texas, United States",
    grade: "A",
    new: true,
    was: {
      title: "Senior Manager, Customer Experience",
      company: "Glowco",
      company_linkedin: "https://www.linkedin.com/company/glowco",
      industry: "",
      start: "2021-03-01",
      end: "2026-08-01",
      months: 65,
    },
    now: {
      title: "VP Customer Experience",
      company: "Newbrand",
      company_linkedin: "",
      industry: "Retail",
      start: "2026-09-01",
      end: null,
      months: 2,
    },
    why: "Runs CX at a consumer brand",
    ...over,
  };
}

export function championsReport(over: Partial<ChampionsReport> = {}): ChampionsReport {
  return {
    kind: "champions",
    company: "CXHero",
    website: "https://cxhero.example",
    built: "2026-11-22",
    icp: {
      sells: "AI agents for customer service at consumer brands",
      industries: ["Consumer brands", "Retail"],
      company_sizes: ["11-500"],
      titles: ["VP Customer Experience"],
      seniority: ["VP"],
      functions: ["Customer Experience"],
    },
    customers: [
      {
        name: "Glowco",
        domain: "glowco.example",
        evidence: "case_study",
        linkedin: "https://www.linkedin.com/company/glowco",
        linkedin_name: "Glowco Inc.",
        industry: "Personal Care",
      },
      { name: "Ghost Co", domain: "", evidence: "logo", linkedin: "", linkedin_name: "", industry: "" },
    ],
    champions: [
      champion(),
      champion({ name: "Riley Example", grade: "B", linkedin: "https://www.linkedin.com/in/riley-example" }),
      champion({ name: "Sam Example", grade: "C", linkedin: "https://www.linkedin.com/in/sam-example" }),
    ],
    more: 0,
    movers: 20,
    repeat: false,
    skipped: { junior: 2, stale_move: 1 },
    watch: [],
    skipped_people: [],
    linkedin_usd: 0,
    ...over,
  };
}

export function championsSummary(over: Partial<ChampionsSummary> = {}): ChampionsSummary {
  return {
    champions: 4,
    a: 2,
    b: 1,
    c: 1,
    new: 4,
    repeat: false,
    customers: 5,
    matched: 4,
    movers: 20,
    watch: 2,
    linkedin_usd: 0.21,
    ...over,
  };
}

/** A finished champion report as the tracker lists it. */
export function championsMagnet(over: Partial<Magnet> = {}): Magnet {
  return {
    id: "m1",
    company_id: null,
    kind: "champions",
    status: "ready",
    title: "CXHero: champion report",
    mode: "teaser",
    website: "https://cxhero.example",
    domain: "cxhero.example",
    step: "",
    error: "",
    created: "2026-11-22T15:00:00Z",
    link: "/m/m1/tok",
    views: 0,
    summary: null,
    champions: championsSummary(),
    ...over,
  };
}
