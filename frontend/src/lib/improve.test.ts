import { describe, expect, it } from "vitest";
import type { SquadPlayer } from "./api";
import { applyImproveSuggestion, DEFAULT_IMPROVE, replacements, toImproveRequest } from "./improve";

const sp = (id: number, score: number | null = 50): SquadPlayer => ({
  player_id: id, name: `P${id}`, age: 25, position: null, role: score == null ? null : "ST", score,
  reliability: null, price_eur: null, minutes_2025_26: 0,
});

describe("toImproveRequest", () => {
  const squad = [sp(1), sp(2), sp(3, null)];
  it("sends only ticked players and locks only squad players", () => {
    const { req } = toImproveRequest(DEFAULT_IMPROVE, squad, new Set([1, 3]), new Set([1, 2]));
    expect(req).toMatchObject({ formation: "4-3-3", budget_eur: 5_000_000, owned_player_ids: [1, 3],
      locked_player_ids: [1], left_player_ids: [2], max_signings: 2, signing_roles: [], min_minutes_next: 900,
      league_ids: [], nationalities: [], score: "adjusted" });
  });
  it("accepts a zero budget to show the current XI", () => {
    expect(toImproveRequest({ ...DEFAULT_IMPROVE, budget: "0" }, squad, new Set([1]), new Set()).req?.budget_eur).toBe(0);
  });
  it("needs a squad and a readable budget", () => {
    const { req, errors } = toImproveRequest({ ...DEFAULT_IMPROVE, budget: "lots" }, squad, new Set(), new Set());
    expect(req).toBeNull();
    expect(Object.keys(errors).sort()).toEqual(["budget", "squad"]);
  });
});

describe("applyImproveSuggestion", () => {
  it("allows more signings and raises the budget when the suggestion says so", () => {
    expect(applyImproveSuggestion(DEFAULT_IMPROVE, "allow 3 signings and raise the budget to €1.2m", null))
      .toMatchObject({ maxSignings: 3, budget: "1.2m" });
    expect(applyImproveSuggestion(DEFAULT_IMPROVE, "allow 1 signing", null)).toMatchObject({ maxSignings: 1, budget: "5m" });
  });
  it("clears the positions to sign", () => {
    expect(applyImproveSuggestion({ ...DEFAULT_IMPROVE, signingRoles: ["ST"] }, "allow signings in any position", null)?.signingRoles).toEqual([]);
  });
  it("ignores changes the form cannot make", () => {
    expect(applyImproveSuggestion(DEFAULT_IMPROVE, "use a different scoring model", null)).toBeNull();
  });
});

describe("replacements", () => {
  it("pairs each signing with the weakest own player of his role who dropped out", () => {
    const current = [
      { player_id: 1, role: "ST", score: 40, name: "Old striker" },
      { player_id: 2, role: "CB", score: 30, name: "Weak CB" },
      { player_id: 3, role: "CB", score: 60, name: "Good CB" },
    ];
    const next = [
      { player_id: 3, role: "CB", score: 60, name: "Good CB", signing: false },
      { player_id: 10, role: "CB", score: 80, name: "New CB", signing: true },
      { player_id: 11, role: "ST", score: 85, name: "New ST", signing: true },
    ];
    const r = replacements(current, next);
    expect(r.get(10)?.name).toBe("Weak CB");
    expect(r.get(11)?.name).toBe("Old striker");
  });
});
