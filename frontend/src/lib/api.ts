// Typed client for the ScoutIQ API. Errors follow the API's format {"error": {code, message, details}}.

export type Role = "GK" | "CB" | "FB" | "CM" | "AW" | "ST";

export interface OptimizeRequest {
  budget_eur: number;
  formation?: string | null;
  squad_size?: number | null;
  needs?: Partial<Record<Role, number>> | null;
  age_min?: number | null;
  age_max?: number | null;
  league_ids?: number[];
  nationalities?: string[];
  max_price_eur?: number | null;
  min_minutes?: number;
  min_minutes_next?: number;
  max_per_club?: number | null;
  alternatives?: number;
  score?: "within" | "adjusted";
}

export interface PlayerOut {
  slot: string;
  player_id: number;
  name: string;
  role: Role;
  score: number;
  price_eur: number;
  valuation_date: string | null;
  age: number | null;
  club_2024_25: string;
  league: string;
  minutes_2024_25: number;
  minutes_2025_26: number;
  reliability: string;
  position_consistent: boolean | null;
}

export interface TeamOut { total_score: number; cost_eur: number; players: PlayerOut[]; }

export interface OptimizeResponse {
  status: "optimal" | "feasible" | "infeasible" | "unknown" | "error";
  budget_eur: number;
  remaining_budget_eur: number | null;
  solve_time_ms: number;
  eligible_players: number;
  team: TeamOut | null;
  alternatives: TeamOut[];
  diagnosis: {
    reason: string;
    cheapest_cost_eur: number | null;
    budget_shortfall_eur: number | null;
    suggestions: { change: string; total_score: number; cost_eur: number; unlock_ids?: number[]; add_roles?: Role[] }[];
  } | null;
  notes: string[];
}

export interface User { id: number; email: string; role: "scout" | "admin"; created_at: string; }

export interface ScenarioSummary {
  id: number; name: string; mode: "build" | "improve"; status: string;
  total_score: number | null; cost_eur: number | null; budget_eur: number; created_at: string;
  club_name: string | null; gain: number | null; signings: number | null;   // improve only
}
export interface BuildScenario extends ScenarioSummary { mode: "build"; request: OptimizeRequest; result: OptimizeResponse; }
export interface ImproveScenario extends ScenarioSummary {
  mode: "improve"; club_id: number | null; request: ImproveRequest; result: ImproveResponse;
}
export type Scenario = BuildScenario | ImproveScenario;

export interface League { id: number; name: string; country: string; scored_players: number; }

export interface PlayerRow {
  player_id: number; name: string; age: number | null; nationality: string | null; role: Role;
  league_id: number; league: string; club: string; score: number; score_adjusted: number | null;
  value_for_money: number | null; reliability: string; minutes: number; minutes_next: number;
  price_eur: number | null; valuation_date: string | null; position_consistent: boolean | null;
}
export interface PlayerPage { total: number; limit: number; offset: number; items: PlayerRow[]; }

export type SortKey = "score" | "price_eur" | "value_for_money" | "age" | "minutes" | "minutes_next" | "name";
export interface PlayerQuery {
  score?: "within" | "adjusted";
  q?: string; role?: Role[]; league_id?: number[]; age_min?: number; age_max?: number; max_price_eur?: number;
  min_minutes?: number; min_minutes_next?: number; sort?: SortKey; order?: "asc" | "desc"; limit?: number; offset?: number;
}

export interface Metric {
  key: string; label: string; kind: "per90" | "rate"; lower_is_better: boolean;
  value: number | null; percentile: number | null; weight: number | null;
}
export interface Score {
  season: number; league_id: number; league: string; role: Role; score: number; score_adjusted: number | null;
  value_for_money: number | null; value_for_money_note: string | null; reliability: string; minutes: number | null;
  weight_coverage: number | null; dropped_metrics: string[];
  position_check: { api_position: string | null; consistent: boolean | null } | null; metrics: Metric[];
}
export interface SeasonStats {
  season: number; club: string; league: string; source: string;
  [field: string]: number | string | null;
}
export interface RecentRow { club: string; league: string; appearances: number | null; minutes: number | null;
  goals: number | null; assists: number | null; cards_yellow: number | null; cards_red: number | null; }
export interface Profile {
  id: number; name: string; birth_date: string | null; age: number | null; nationality: string | null;
  foot: string | null; height_cm: number | null; primary_position: string | null; secondary_position: string | null;
  market_value: { value_eur: number; valuation_date: string; source: string } | null;
  value_history: { date: string; value_eur: number }[];
  scores: Score[];
  season_stats: SeasonStats[];
  recent_form: { season: number; source: string; rows: RecentRow[];
    totals: { appearances: number; minutes: number; goals: number; assists: number; cards_yellow: number; cards_red: number } | null };
}
export interface DashboardLeague {
  id: number; name: string; country: string; status: "complete" | "provisional" | "no_data";
  coverage: number; scored: number; regulars: number; median_value_eur: number | null; roles: Record<string, number>;
  strength: number | null;
}
export interface Dashboard {
  season: number; recent_season: number; max_age: number | null;
  totals: { players_scored: number; regulars_scored: number; still_playing: number; leagues_complete: number;
    leagues_enabled: number; latest_valuation_date: string | null };
  leagues: DashboardLeague[];
  strength_source: string | null;
  imports: { source: string; kind: string; status: string; finished_at: string | null; rows_written: number; requests_used: number }[];
  model: { version: string | null; league_adjustment: { accepted: boolean; reason: string; source?: string | null } | null };
  value_picks: Record<Role, PlayerRow[]>;
  value_for_money_shown: Record<Role, boolean>;
  budget_picks: Record<string, Record<Role, PlayerRow[]>>; // price cap in EUR -> role -> players
}

export interface Club { id: number; name: string; league: string; }
export interface SquadPlayer {
  player_id: number; name: string; age: number | null; position: string | null; role: Role | null;
  score: number | null; reliability: string | null; price_eur: number | null; minutes_2025_26: number;
}
export interface Squad { club: Club; players: SquadPlayer[]; }

export interface ImproveRequest {
  formation: string; budget_eur: number; owned_player_ids: number[]; locked_player_ids?: number[]; left_player_ids?: number[];
  max_signings?: number; signing_roles?: Role[]; nationalities?: string[]; league_ids?: number[]; age_min?: number | null; age_max?: number | null; max_price_eur?: number | null;
  min_minutes?: number; min_minutes_next?: number; alternatives?: number; score?: "within" | "adjusted";
}
export interface ImprovePlayer extends PlayerOut { signing: boolean; }
export interface ImproveTeam { total_score: number; cost_eur: number; players: ImprovePlayer[]; }
export interface ImproveResponse {
  status: OptimizeResponse["status"]; budget_eur: number; remaining_budget_eur: number | null;
  solve_time_ms: number; eligible_players: number;
  current: ImproveTeam | null; current_missing: Partial<Record<Role, number>>;
  team: ImproveTeam | null; gain: number | null; alternatives: ImproveTeam[];
  diagnosis: OptimizeResponse["diagnosis"]; unscored: { player_id: number; name: string }[]; notes: string[];
}

export interface AssistantFilters {
  roles: Role[]; role_counts: Partial<Record<Role, number>>; age_min: number | null; age_max: number | null;
  max_price_eur: number | null; budget_eur: number | null; leagues: string[]; nationalities: string[];
  still_playing: boolean | null; include_low_minutes: boolean | null; formation: string | null;
}
export interface Interpretation {
  engine: "ai" | "rules"; filters: AssistantFilters; league_ids: number[];
  understood: string[]; not_applied: string[]; note: string | null;
}

export interface Comparison { players: Profile[]; same_role: boolean; }

function query(params: Record<string, unknown>): string {
  const u = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v == null || v === "") continue;
    if (Array.isArray(v)) v.forEach((x) => u.append(k, String(x)));
    else u.set(k, String(v));
  }
  const s = u.toString();
  return s ? `?${s}` : "";
}

export class ApiError extends Error {
  constructor(public status: number, message: string, public details: { field: string; message: string }[] = []) {
    super(message);
  }
}

const BASE = "/api/v1";
let token: string | null = null;
let onUnauthorized: () => void = () => {};

export function setToken(t: string | null) { token = t; }
export function setUnauthorizedHandler(fn: () => void) { onUnauthorized = fn; }

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (init.body && typeof init.body === "string") headers.set("Content-Type", "application/json");
  let res: Response;
  try {
    res = await fetch(BASE + path, { ...init, headers });
  } catch {
    throw new ApiError(0, "The ScoutIQ server is not reachable. Check that Docker is running.");
  }
  if (res.status === 204) return undefined as T;
  const body = await res.json().catch(() => null);
  if (!res.ok) {
    if (res.status === 401 && token) onUnauthorized();
    const err = body?.error;
    // a failed login follows OAuth2: {"error": "invalid_grant", "error_description": "..."}
    if (typeof err === "string") throw new ApiError(res.status, body.error_description ?? err);
    throw new ApiError(res.status, err?.message ?? `Request failed (${res.status})`, err?.details ?? []);
  }
  return body as T;
}

/** Download a file the server makes (e.g. a PDF report) and save it in the browser. */
async function download(path: string, fallbackName: string): Promise<void> {
  const headers = new Headers();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  let res: Response;
  try {
    res = await fetch(BASE + path, { headers });
  } catch {
    throw new ApiError(0, "The ScoutIQ server is not reachable. Check that Docker is running.");
  }
  if (!res.ok) {
    if (res.status === 401 && token) onUnauthorized();
    const body = await res.json().catch(() => null);
    throw new ApiError(res.status, body?.error?.message ?? `Download failed (${res.status})`);
  }
  const name = /filename="([^"]+)"/.exec(res.headers.get("Content-Disposition") ?? "")?.[1] ?? fallbackName;
  const url = URL.createObjectURL(await res.blob());
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export const api = {
  register: (email: string, password: string) =>
    request<User>("/auth/register", { method: "POST", body: JSON.stringify({ email, password }) }),
  login: (email: string, password: string) =>
    request<{ access_token: string; expires_in_minutes: number }>("/auth/login", {
      method: "POST",
      body: new URLSearchParams({ username: email, password }),
    }),
  me: () => request<User>("/auth/me"),
  optimize: (req: OptimizeRequest) =>
    request<OptimizeResponse>("/optimize/squad", { method: "POST", body: JSON.stringify(req) }),
  saveScenario: (name: string, req: OptimizeRequest) =>
    request<BuildScenario>("/scenarios", { method: "POST", body: JSON.stringify({ name, request: req }) }),
  saveImproveScenario: (name: string, clubId: number | null, req: ImproveRequest) =>
    request<ImproveScenario>("/scenarios/improve", { method: "POST", body: JSON.stringify({ name, club_id: clubId, request: req }) }),
  scenarios: () => request<ScenarioSummary[]>("/scenarios"),
  scenario: (id: number) => request<Scenario>(`/scenarios/${id}`),
  deleteScenario: (id: number) => request<void>(`/scenarios/${id}`, { method: "DELETE" }),
  downloadScenarioPdf: (id: number) => download(`/scenarios/${id}/report.pdf`, `scoutiq-scenario-${id}.pdf`),
  leagues: () => request<League[]>("/leagues"),
  players: (q: PlayerQuery) => request<PlayerPage>(`/players${query({ ...q })}`),
  player: (id: number) => request<Profile>(`/players/${id}`),
  adjustment: () => request<{ active: boolean; source: string | null; reason: string | null }>("/stats/adjustment"),
  dashboard: (maxAge?: number | null) => request<Dashboard>(`/stats/dashboard${query({ max_age: maxAge ?? undefined })}`),
  clubs: (q: string) => request<Club[]>(`/clubs${query({ q })}`),
  squad: (clubId: number) => request<Squad>(`/clubs/${clubId}/squad`),
  squadPlayers: (ids: number[]) => request<SquadPlayer[]>(`/squad/players${query({ ids })}`),
  interpret: (text: string, page: "players" | "builder" | "improve") =>
    request<Interpretation>("/assistant/interpret", { method: "POST", body: JSON.stringify({ text, page }) }),
  improve: (body: ImproveRequest) => request<ImproveResponse>("/optimize/improve", { method: "POST", body: JSON.stringify(body) }),
  compare: (ids: number[]) => request<Comparison>(`/players/compare${query({ ids })}`),
};
