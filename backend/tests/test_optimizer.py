"""Optimizer correctness tests (Phase 5 model document, "Baselines and verification").

Candidates here are generated (clearly synthetic "P<id>" players), because these tests
check the mathematics: exact optimality against brute force, constraint satisfaction,
baselines never beating the optimizer, alternatives, infeasibility diagnosis and Mode B.
"""

import random
import time
from datetime import date

import pytest

from app.optimization.baselines import best_affordable_per_position, brute_force, greedy_value, random_feasible
from app.optimization.model import (
    FORMATIONS,
    ROLES,
    Candidate,
    Request,
    formation_request,
    positions_request,
    squad_request,
)
from app.optimization.solver import solve, solve_once
from app.optimization.verify import verify

REF = date(2026, 11, 5)


def make_pool(n_per_role: int, seed: int, clubs: int = 8) -> list[Candidate]:
    rng = random.Random(seed)
    pool, pid = [], 0
    for role in ROLES:
        for _ in range(n_per_role):
            pid += 1
            pool.append(Candidate(
                player_id=pid, name=f"P{pid}", role=role, score=round(rng.uniform(5, 99), 1),
                price=rng.choice([25, 50, 100, 200, 400, 800, 1500, 3000, 6000, 12000, 25000]) * 1000,
                league_id=rng.randint(1, 3), league=f"L{pid % 3}", club_id=rng.randint(1, clubs),
                nationality=rng.choice(["AAA", "BBB", "CCC"]), birth_date=date(rng.randint(1990, 2006), 6, 15),
                minutes=rng.choice([600, 1200, 2400, 3000]), minutes_next=rng.choice([0, 500, 1500, 2500]),
            ))
    return pool


def small_request(rng: random.Random, **kw) -> Request:
    needs = {r: rng.randint(0, 2) for r in ROLES}
    if sum(needs.values()) == 0:
        needs["ST"] = 1
    budget = rng.choice([200, 500, 1000, 3000, 8000, 20000, 60000]) * 1000
    return positions_request(needs, budget, min_minutes=0, alternatives=0, reference_date=REF, **kw)


# ---------- exact optimality ----------

@pytest.mark.parametrize("seed", range(200))
def test_optimizer_equals_brute_force(seed):
    rng = random.Random(seed)
    pool = make_pool(4, seed)
    req = small_request(rng, max_per_club=rng.choice([None, None, 1, 2]))
    status, team = solve_once(pool, [], req)
    best = brute_force(pool, req)
    if best is None:
        assert team is None and status == "infeasible"
    else:
        assert team is not None and status == "optimal"
        assert team.total_score == pytest.approx(best.total_score)
        assert team.cost == best.cost  # stage 2: cheapest among the best
        assert verify(team, req) == []


# ---------- the case sorting gets wrong ----------

def _c(pid, role, score, price):
    return Candidate(player_id=pid, name=f"P{pid}", role=role, score=score, price=price * 1_000_000,
                     league_id=1, league="L", minutes=3000)


def test_budget_interaction_beats_greedy_methods():
    # 1 CB + 1 ST for EUR 10m. Taking the best CB first (X) leaves only the weak striker.
    pool = [_c(1, "CB", 80, 9), _c(2, "CB", 75, 2), _c(3, "ST", 90, 8), _c(4, "ST", 60, 1)]
    req = positions_request({"CB": 1, "ST": 1}, 10_000_000, alternatives=0)
    sol = solve(pool, req)
    assert {p.player_id for p in sol.team.players} == {2, 3}          # 75 + 90 = 165
    assert best_affordable_per_position(pool, req).total_score == 140  # 80 + 60
    assert greedy_value(pool, req).total_score == 135                  # 60 + 75


@pytest.mark.parametrize("seed", range(40))
def test_baselines_are_valid_and_never_better(seed):
    rng = random.Random(1000 + seed)
    pool = make_pool(12, seed)
    req = formation_request(rng.choice(list(FORMATIONS)), rng.choice([5, 20, 60, 150]) * 1_000_000,
                            min_minutes=0, alternatives=0, reference_date=REF)
    sol = solve(pool, req, diagnose_on_failure=False)
    for method in (best_affordable_per_position, greedy_value, random_feasible):
        team = method(pool, req)
        if team is None:
            continue
        assert verify(team, req) == [], method.__name__
        assert sol.team is not None and team.total_score <= sol.team.total_score + 1e-9, method.__name__


# ---------- requests from the brief ----------

def test_brief_example_500k_striker_midfielder_centre_back():
    pool = make_pool(30, seed=5)
    req = positions_request({"ST": 1, "CM": 1, "CB": 1}, 500_000, min_minutes=0, reference_date=REF)
    sol = solve(pool, req)
    assert sol.status == "optimal" and sol.violations == []
    assert sorted(p.role for p in sol.team.players) == ["CB", "CM", "ST"]
    assert sol.team.cost <= 500_000 and sol.remaining_budget == 500_000 - sol.team.cost


def test_full_xi_and_alternatives():
    pool = make_pool(40, seed=6)
    req = formation_request("4-3-3", 15_000_000, min_minutes=0, alternatives=3, reference_date=REF)
    sol = solve(pool, req)
    assert sol.status == "optimal" and len(sol.team.players) == 11
    teams = [sol.team] + sol.alternatives
    assert len(sol.alternatives) == 3
    assert len({frozenset(t.ids()) for t in teams}) == 4                       # all different
    assert all(a.total_score >= b.total_score for a, b in zip(teams, teams[1:]))  # best first


def test_complete_squad():
    pool = make_pool(60, seed=7)
    req = squad_request("4-4-2", 80_000_000, size=22, min_minutes=0, reference_date=REF)
    sol = solve(pool, req)
    assert sol.status == "optimal" and len(sol.team.players) == 22 and sol.violations == []


# ---------- filters and constraints ----------

def test_filters_are_respected():
    pool = make_pool(40, seed=8)
    req = formation_request("4-2-3-1", 40_000_000, age_max=25, max_price=5_000_000, league_ids=(1, 2),
                            nationalities=("AAA", "BBB"), min_minutes=1200, min_minutes_next=500,
                            max_per_club=2, reference_date=REF)
    sol = solve(pool, req)
    if sol.team:
        assert verify(sol.team, req) == []
        assert all(p.price <= 5_000_000 and p.league_id in (1, 2) for p in sol.team.players)


def test_verifier_catches_a_bad_team():
    pool = make_pool(5, seed=9)
    req = positions_request({"ST": 2}, 1_000, min_minutes=0)
    from app.optimization.model import Team
    bad = Team([p for p in pool if p.role == "CB"][:2])
    problems = verify(bad, req)
    assert any("ST" in p for p in problems) and any("exceeds budget" in p for p in problems)


# ---------- infeasibility ----------

def test_too_few_players_in_a_role_is_explained():
    pool = make_pool(10, seed=10)
    req = positions_request({"GK": 3}, 100_000_000, nationalities=("AAA",), min_minutes=2400, reference_date=REF)
    sol = solve(pool, req)
    assert sol.status == "infeasible" and sol.team is None
    assert sol.diagnosis["shortages"] and "goalkeepers" in sol.diagnosis["reason"]
    assert any("nationality" in s["change"] or "low-reliability" in s["change"] for s in sol.diagnosis["suggestions"])


def test_budget_too_small_gives_shortfall_and_checked_suggestion():
    pool = make_pool(20, seed=11)
    req = formation_request("4-3-3", 10_000, min_minutes=0, reference_date=REF)
    sol = solve(pool, req)
    d = sol.diagnosis
    assert sol.status == "infeasible" and d["budget_shortfall"] > 0
    raise_budget = next(s for s in d["suggestions"] if s["change"].startswith("increase the budget"))
    assert raise_budget["cost"] <= d["cheapest_cost"]  # the suggestion was actually solved, not guessed


# ---------- Mode B ----------

def test_mode_b_keeps_squad_and_buys_only_what_is_asked():
    pool = make_pool(30, seed=12)
    squad = [p for p in pool if p.role != "ST"][:10]  # current squad: 10 players, no striker
    needs = {"ST": 1, "CM": 1}
    counts = {r: sum(1 for p in squad if p.role == r) + needs.get(r, 0) for r in ROLES}
    req = Request(budget=3_000_000, role_min=counts, role_max=counts, squad_size=len(squad) + 2, mode="improve",
                  kept_ids=tuple(p.player_id for p in squad), exclude_ids=tuple(p.player_id for p in squad),
                  min_minutes=0, reference_date=REF)
    sol = solve(pool, req, kept=squad)
    assert sol.status == "optimal" and sol.violations == []
    assert {p.player_id for p in squad} <= sol.team.ids()
    assert sorted(p.role for p in sol.team.signings) == ["CM", "ST"]
    assert sol.team.cost == sum(p.price for p in sol.team.signings) <= 3_000_000  # kept players cost nothing


# ---------- performance (NFR-03) ----------

def test_full_pool_solves_fast():
    pool = make_pool(500, seed=13)  # 3,000 candidates
    req = formation_request("4-3-3", 30_000_000, min_minutes=0, alternatives=0, reference_date=REF)
    start = time.perf_counter()
    sol = solve(pool, req)
    assert sol.status == "optimal"
    assert time.perf_counter() - start < 5
