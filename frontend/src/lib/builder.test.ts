import { describe as suite, expect, it } from "vitest";
import { DEFAULT_FORM, applySuggestion, fromRequest, toRequest } from "./builder";

suite("toRequest", () => {
  it("builds a starting XI request with the default filters", () => {
    const { req, errors } = toRequest(DEFAULT_FORM);
    expect(errors).toEqual({});
    expect(req).toMatchObject({ budget_eur: 15_000_000, formation: "4-3-3", min_minutes: 900, min_minutes_next: 900 });
    expect(req?.needs).toBeUndefined();
  });
  it("sends only the positions asked for in signings mode", () => {
    const { req } = toRequest({ ...DEFAULT_FORM, mode: "signings", budget: "500k" });
    expect(req).toMatchObject({ budget_eur: 500_000, needs: { ST: 1, CM: 1, CB: 1 } });
    expect(req?.formation).toBeUndefined();
  });
  it("reports unreadable money and impossible ages", () => {
    const { req, errors } = toRequest({ ...DEFAULT_FORM, budget: "lots", ageMin: "30", ageMax: "25" });
    expect(req).toBeNull();
    expect(Object.keys(errors).sort()).toEqual(["ageMax", "budget"]);
  });
  it("asks for a unit when a bare small number is typed", () => {
    const { req, errors } = toRequest({ ...DEFAULT_FORM, budget: "30" });
    expect(req).toBeNull();
    expect(errors.budget).toContain("30m");
  });
  it("switches the 2025/26 filter off with 0", () => {
    expect(toRequest({ ...DEFAULT_FORM, recentForm: false }).req?.min_minutes_next).toBe(0);
  });
});

suite("fromRequest", () => {
  it("round-trips a request", () => {
    const f = { ...DEFAULT_FORM, mode: "signings" as const, budget: "2.5m", ageMax: "27", maxPrice: "900k" };
    expect(toRequest(fromRequest(toRequest(f).req!)).req).toEqual(toRequest(f).req);
  });
});

suite("applySuggestion", () => {
  const d = { reason: "", cheapest_cost_eur: 1_900_000, budget_shortfall_eur: 1_400_000, suggestions: [] };
  it("raises the budget to the cheapest feasible cost", () => {
    expect(applySuggestion(DEFAULT_FORM, "increase the budget to €1.9m", d)?.budget).toBe("1.9m");
  });
  it("widens the age range", () => {
    expect(applySuggestion(DEFAULT_FORM, "widen the age range to any-29", d)).toMatchObject({ ageMin: "", ageMax: "29" });
  });
  it("returns null for changes the form cannot make", () => {
    expect(applySuggestion(DEFAULT_FORM, "search all supported leagues", d)).toBeNull();
  });
});
