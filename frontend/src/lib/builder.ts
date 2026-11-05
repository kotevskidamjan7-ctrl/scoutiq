// Squad-builder form state, and how it turns into an API request (and back, for reopened scenarios).
import type { OptimizeRequest, OptimizeResponse, Role } from "./api";
import { eur, parseMoney } from "./format";

export type Mode = "xi" | "signings";

export interface Form {
  mode: Mode;
  budget: string;
  formation: string;
  needs: Record<Role, number>;
  ageMin: string;
  ageMax: string;
  maxPrice: string;
  maxPerClub: string;
  includeLowMinutes: boolean;   // min_minutes 450 instead of 900
  recentForm: boolean;          // min_minutes_next 900 instead of 0
}

export const EMPTY_NEEDS: Record<Role, number> = { GK: 0, CB: 0, FB: 0, CM: 0, AW: 0, ST: 0 };

export const DEFAULT_FORM: Form = {
  mode: "xi", budget: "15m", formation: "4-3-3", needs: { ...EMPTY_NEEDS, ST: 1, CM: 1, CB: 1 },
  ageMin: "", ageMax: "", maxPrice: "", maxPerClub: "", includeLowMinutes: false, recentForm: true,
};

const int = (s: string) => (s.trim() === "" ? null : Number.parseInt(s, 10));

/** Returns the request, or a list of problems to show beside the fields. */
export function toRequest(f: Form): { req: OptimizeRequest | null; errors: Record<string, string> } {
  const errors: Record<string, string> = {};
  const budget = parseMoney(f.budget);
  if (budget == null) errors.budget = "Write the budget like 15m, 500k or 2,500,000.";
  else if (budget < 10_000) errors.budget = `Add m for millions or k for thousands, for example ${f.budget.trim()}m.`;
  const maxPrice = f.maxPrice.trim() ? parseMoney(f.maxPrice) : null;
  if (f.maxPrice.trim() && maxPrice == null) errors.maxPrice = "Write the price like 3m or 750k.";
  const ageMin = int(f.ageMin), ageMax = int(f.ageMax);
  for (const [k, v] of [["ageMin", ageMin], ["ageMax", ageMax]] as const)
    if (v != null && (Number.isNaN(v) || v < 15 || v > 45)) errors[k] = "Ages from 15 to 45.";
  if (ageMin != null && ageMax != null && ageMin > ageMax) errors.ageMax = "The maximum age is below the minimum.";
  const perClub = int(f.maxPerClub);
  if (perClub != null && (Number.isNaN(perClub) || perClub < 1 || perClub > 11)) errors.maxPerClub = "From 1 to 11.";
  const totalNeeds = Object.values(f.needs).reduce((a, b) => a + b, 0);
  if (f.mode === "signings" && totalNeeds === 0) errors.needs = "Add at least one position to sign.";
  if (Object.keys(errors).length) return { req: null, errors };

  const req: OptimizeRequest = {
    budget_eur: budget!,
    age_min: ageMin, age_max: ageMax, max_price_eur: maxPrice, max_per_club: perClub,
    min_minutes: f.includeLowMinutes ? 450 : 900,
    min_minutes_next: f.recentForm ? 900 : 0,
    alternatives: 2,
  };
  if (f.mode === "xi") req.formation = f.formation;
  else req.needs = Object.fromEntries(Object.entries(f.needs).filter(([, n]) => n > 0));
  return { req, errors };
}

const money = (n: number) => (n >= 1_000_000 ? `${+(n / 1_000_000).toFixed(2)}m` : n >= 1_000 ? `${Math.round(n / 1_000)}k` : `${n}`);

export function fromRequest(r: OptimizeRequest): Form {
  return {
    mode: r.formation ? "xi" : "signings",
    budget: money(r.budget_eur),
    formation: r.formation ?? DEFAULT_FORM.formation,
    needs: { ...EMPTY_NEEDS, ...(r.needs ?? {}) },
    ageMin: r.age_min?.toString() ?? "", ageMax: r.age_max?.toString() ?? "",
    maxPrice: r.max_price_eur ? money(r.max_price_eur) : "",
    maxPerClub: r.max_per_club?.toString() ?? "",
    includeLowMinutes: (r.min_minutes ?? 900) < 900,
    recentForm: (r.min_minutes_next ?? 900) > 0,
  };
}

/** Turn a diagnosis suggestion (written by the server, each one checked by re-solving) into a form change. */
export function applySuggestion(f: Form, change: string, d: OptimizeResponse["diagnosis"]): Form | null {
  if (change.startsWith("increase the budget") && d?.cheapest_cost_eur) return { ...f, budget: money(d.cheapest_cost_eur) };
  const age = change.match(/^widen the age range to (\w+)-(\w+)/);
  if (age) return { ...f, ageMin: age[1] === "any" ? "" : age[1], ageMax: age[2] === "any" ? "" : age[2] };
  if (change.startsWith("remove the maximum price")) return { ...f, maxPrice: "" };
  if (change.startsWith("include low-reliability")) return { ...f, includeLowMinutes: true };
  if (change.startsWith("remove the 2025/26 minutes")) return { ...f, recentForm: false };
  if (change.startsWith("remove the limit per club")) return { ...f, maxPerClub: "" };
  return null; // league and nationality filters are not in this form yet
}

export function describe(r: OptimizeRequest): string {
  const what = r.formation
    ? `Starting XI, ${r.formation}`
    : Object.entries(r.needs ?? {}).map(([role, n]) => `${n} ${role}`).join(" + ");
  return `${what}, budget ${eur(r.budget_eur)}`;
}
