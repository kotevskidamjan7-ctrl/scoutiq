// Club improvement form state and how it becomes a request (and how diagnosis suggestions change it).
import type { ImproveRequest, ImproveResponse, Role, SquadPlayer } from "./api";
import { parseMoney } from "./format";

// players per role in each formation (same as the server's FORMATIONS)
export const ROLE_COUNTS: Record<string, Record<string, number>> = {
  "4-3-3": { GK: 1, CB: 2, FB: 2, CM: 3, AW: 2, ST: 1 },
  "4-2-3-1": { GK: 1, CB: 2, FB: 2, CM: 2, AW: 3, ST: 1 },
  "4-4-2": { GK: 1, CB: 2, FB: 2, CM: 2, AW: 2, ST: 2 },
  "3-5-2": { GK: 1, CB: 3, FB: 2, CM: 3, AW: 0, ST: 2 },
  "3-4-3": { GK: 1, CB: 3, FB: 2, CM: 2, AW: 2, ST: 1 },
};

export interface ImproveForm {
  formation: string;
  budget: string;
  maxSignings: number;
  signingRoles: Role[];   // empty = any position
  ageMin: string;
  ageMax: string;
  maxPrice: string;
  recentForm: boolean;
  includeLowMinutes: boolean;
}

export const DEFAULT_IMPROVE: ImproveForm = {
  formation: "4-3-3", budget: "5m", maxSignings: 2, signingRoles: [], ageMin: "", ageMax: "", maxPrice: "",
  recentForm: true, includeLowMinutes: false,
};

const int = (s: string) => (s.trim() === "" ? null : Number.parseInt(s, 10));

export function toImproveRequest(f: ImproveForm, squad: SquadPlayer[], inSquad: Set<number>, locked: Set<number>):
  { req: ImproveRequest | null; errors: Record<string, string> } {
  const errors: Record<string, string> = {};
  const budget = f.budget.trim() === "0" ? 0 : parseMoney(f.budget);
  if (budget == null) errors.budget = "Write the budget like 5m, 500k or 0.";
  else if (budget > 0 && budget < 10_000) errors.budget = `Add m for millions or k for thousands, for example ${f.budget.trim()}m.`;
  const maxPrice = f.maxPrice.trim() ? parseMoney(f.maxPrice) : null;
  if (f.maxPrice.trim() && maxPrice == null) errors.maxPrice = "Write the price like 3m or 750k.";
  const ageMin = int(f.ageMin), ageMax = int(f.ageMax);
  for (const [k, v] of [["ageMin", ageMin], ["ageMax", ageMax]] as const)
    if (v != null && (Number.isNaN(v) || v < 15 || v > 45)) errors[k] = "Ages from 15 to 45.";
  if (ageMin != null && ageMax != null && ageMin > ageMax) errors.ageMax = "The oldest age is below the youngest.";
  const owned = squad.filter((p) => inSquad.has(p.player_id)).map((p) => p.player_id);
  if (owned.length === 0) errors.squad = "Pick your club or add at least one player to the squad.";
  if (Object.keys(errors).length) return { req: null, errors };
  return {
    errors,
    req: {
      formation: f.formation, budget_eur: budget!, owned_player_ids: owned,
      locked_player_ids: owned.filter((id) => locked.has(id)), max_signings: f.maxSignings,
      left_player_ids: squad.filter((p) => !inSquad.has(p.player_id)).map((p) => p.player_id),
      signing_roles: f.signingRoles,
      age_min: ageMin, age_max: ageMax, max_price_eur: maxPrice,
      min_minutes: f.includeLowMinutes ? 450 : 900, min_minutes_next: f.recentForm ? 900 : 0, alternatives: 2,
    },
  };
}

const money = (n: number) => (n >= 1_000_000 ? `${+(n / 1_000_000).toFixed(2)}m` : n >= 1_000 ? `${Math.round(n / 1_000)}k` : `${n}`);

/** Turn a server suggestion (each one checked by re-solving) into a form change; null if the form cannot make it. */
export function applyImproveSuggestion(f: ImproveForm, change: string, d: ImproveResponse["diagnosis"]): ImproveForm | null {
  const more = change.match(/^allow (\d+) signings?(?: and raise the budget to (.+))?$/);
  if (more) {
    const budget = more[2] ? parseMoney(more[2]) : null;
    return { ...f, maxSignings: Number(more[1]), budget: budget != null ? money(budget) : f.budget };
  }
  if (change.startsWith("increase the budget") && d?.cheapest_cost_eur) return { ...f, budget: money(d.cheapest_cost_eur) };
  const age = change.match(/^widen the age range to (\w+)-(\w+)/);
  if (age) return { ...f, ageMin: age[1] === "any" ? "" : age[1], ageMax: age[2] === "any" ? "" : age[2] };
  if (change.startsWith("remove the maximum price")) return { ...f, maxPrice: "" };
  if (change.startsWith("include low-reliability")) return { ...f, includeLowMinutes: true };
  if (change.startsWith("remove the 2025/26 minutes")) return { ...f, recentForm: false };
  if (change === "allow signings in any position") return { ...f, signingRoles: [] };
  return null;
}

/** For each signing, the own player he takes the place of in the starting XI (same role, weakest first). */
export function replacements(current: { player_id: number; role: string; score: number; name: string }[],
                             next: { player_id: number; role: string; score: number; name: string; signing: boolean }[]) {
  const nextIds = new Set(next.map((p) => p.player_id));
  const out = new Map<number, { name: string; score: number } | null>();
  const dropped = current.filter((p) => !nextIds.has(p.player_id)).sort((a, b) => a.score - b.score);
  for (const s of next.filter((p) => p.signing).sort((a, b) => b.score - a.score)) {
    const i = dropped.findIndex((d) => d.role === s.role);
    out.set(s.player_id, i >= 0 ? dropped.splice(i, 1)[0] : null);
  }
  return out;
}
