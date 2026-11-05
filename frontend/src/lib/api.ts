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
    suggestions: { change: string; total_score: number; cost_eur: number }[];
  } | null;
  notes: string[];
}

export interface User { id: number; email: string; role: "scout" | "admin"; created_at: string; }

export interface ScenarioSummary {
  id: number; name: string; mode: string; status: string;
  total_score: number | null; cost_eur: number | null; budget_eur: number; created_at: string;
}
export interface Scenario extends ScenarioSummary { request: OptimizeRequest; result: OptimizeResponse; }

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
    throw new ApiError(res.status, err?.message ?? `Request failed (${res.status})`, err?.details ?? []);
  }
  return body as T;
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
    request<Scenario>("/scenarios", { method: "POST", body: JSON.stringify({ name, request: req }) }),
  scenarios: () => request<ScenarioSummary[]>("/scenarios"),
  scenario: (id: number) => request<Scenario>(`/scenarios/${id}`),
  deleteScenario: (id: number) => request<void>(`/scenarios/${id}`, { method: "DELETE" }),
};
