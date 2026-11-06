"""Mode B (improve an existing club): owned players are free and optional, locked players must start,
and at most S players are bought. Checked against an independent brute force that shares no code
with the solver.
"""

import itertools
import random
from dataclasses import replace
from datetime import date

import pytest

from app.optimization.model import FORMATIONS, ROLES, Candidate, formation_request
from app.optimization.solver import solve
from app.optimization.verify import verify
from tests.test_optimizer import REF, make_pool


def best_xi(players: list[Candidate], counts: dict[str, int]) -> float | None:
    """Best XI from a fixed set of players: roles are independent, so the top-k per role is exact."""
    total = 0.0
    for r, k in counts.items():
        scores = sorted((p.score for p in players if p.role == r), reverse=True)
        if len(scores) < k:
            return None
        total += sum(scores[:k])
    return round(total, 1)


def brute_force_improve(owned, market, counts, budget, max_signings, locked=()):
    """Try every set of at most S signings that fits the budget; keep the best XI that includes the locked players."""
    best = None
    for k in range(max_signings + 1):
        for buy in itertools.combinations(market, k):
            if sum(c.price for c in buy) > budget:
                continue
            players = list(owned) + list(buy)
            # locked players start: take them first, then the best of the rest per role
            total, ok = 0.0, True
            for r, n in counts.items():
                lk = [p.score for p in players if p.role == r and p.player_id in locked]
                rest = sorted((p.score for p in players if p.role == r and p.player_id not in locked), reverse=True)
                if len(lk) > n or len(lk) + len(rest) < n:
                    ok = False
                    break
                total += sum(lk) + sum(rest[: n - len(lk)])
            # every signing must actually start, otherwise a cheaper subset is as good: only count real XIs
            if ok and (best is None or round(total, 1) > best):
                best = round(total, 1)
    return best


def club(seed: int, size: int = 20) -> list[Candidate]:
    """A synthetic club squad: every role covered, weaker than the market on average."""
    rng = random.Random(seed + 10_000)
    squad, pid = [], 900_000
    roles = list(ROLES) * 3 + [rng.choice(ROLES) for _ in range(size - 18)]  # every formation can be filled
    for role in roles:
        pid += 1
        squad.append(Candidate(player_id=pid, name=f"Own{pid}", role=role, score=round(rng.uniform(5, 70), 1),
                               price=0, league_id=9, league="Own league", club_id=999, birth_date=date(1995, 1, 1)))
    return squad


@pytest.mark.parametrize("seed", range(60))
def test_improve_equals_brute_force(seed):
    rng = random.Random(seed)
    formation = rng.choice(list(FORMATIONS))
    counts = {r: n for r, n in FORMATIONS[formation].items() if n}
    owned = club(seed)
    market = [replace(c, minutes=2000) for c in make_pool(2, seed)]  # small market keeps brute force fast
    budget = rng.choice([0, 300, 1000, 5000, 20000]) * 1000
    s = rng.choice([0, 1, 2])
    locked = tuple(rng.sample([o.player_id for o in owned], rng.choice([0, 0, 1])))
    req = formation_request(formation, budget, owned_ids=tuple(o.player_id for o in owned), max_signings=s,
                            kept_ids=locked, min_minutes=0, alternatives=0, reference_date=REF)
    kept = [o for o in owned if o.player_id in locked]
    sol = solve(market, req, kept=kept, owned=owned, diagnose_on_failure=False)
    expected = brute_force_improve(owned, market, counts, budget, s, locked)
    if expected is None:
        assert sol.team is None
        return
    assert sol.team is not None, f"brute force found {expected}"
    assert sol.team.total_score == pytest.approx(expected, abs=0.05)
    assert verify(sol.team, req, kept, owned) == []
    assert len(sol.team.signings) <= s
    assert sol.team.cost <= budget


def test_no_budget_gives_the_current_best_xi():
    owned = club(1)
    req = formation_request("4-3-3", 0, owned_ids=tuple(o.player_id for o in owned), max_signings=3,
                            min_minutes=0, alternatives=0, reference_date=REF)
    sol = solve(make_pool(3, 1), req, owned=owned, diagnose_on_failure=False)
    assert sol.team.signings == [] and sol.team.cost == 0
    assert sol.team.total_score == best_xi(owned, FORMATIONS["4-3-3"])


def test_a_signing_starts_only_when_better_than_the_own_player():
    own = [Candidate(player_id=1000 + i, name=f"Own{i}", role=r, score=50.0, price=0, league_id=9, league="X", club_id=9)
           for i, r in enumerate(["GK", "CB", "CB", "FB", "FB", "CM", "CM", "CM", "AW", "AW", "ST"])]
    worse = Candidate(player_id=1, name="Worse striker", role="ST", score=40.0, price=100_000, league_id=1, league="L",
                      minutes=2000)
    better = Candidate(player_id=2, name="Better striker", role="ST", score=80.0, price=900_000, league_id=1, league="L",
                       minutes=2000)
    owned_ids = tuple(o.player_id for o in own)
    req = formation_request("4-3-3", 1_000_000, owned_ids=owned_ids, max_signings=1, min_minutes=0, alternatives=0)
    sol = solve([worse, better], req, owned=own, diagnose_on_failure=False)
    assert [p.name for p in sol.team.signings] == ["Better striker"]
    assert sol.team.total_score == pytest.approx(50 * 10 + 80)
    cheap = req.relaxed(budget=500_000)
    sol = solve([worse, better], cheap, owned=own, diagnose_on_failure=False)
    assert sol.team.signings == []          # the only affordable striker is worse than the own one


def test_own_players_are_never_bought_or_filtered():
    owned = club(3)
    old = replace(owned[0], birth_date=date(1980, 1, 1), minutes=0)  # would fail age and minutes filters
    owned = [old] + owned[1:]
    req = formation_request("4-3-3", 5_000_000, owned_ids=tuple(o.player_id for o in owned), max_signings=2,
                            age_max=30, min_minutes=900, alternatives=0, reference_date=REF)
    market = make_pool(3, 3) + [replace(old, price=1000)]           # the same player also listed on the market
    sol = solve(market, req, owned=owned, diagnose_on_failure=False)
    assert old.player_id not in {p.player_id for p in sol.team.signings}
    assert verify(sol.team, req, [], owned) == []


def test_infeasible_squad_suggests_more_signings():
    no_keeper = [o for o in club(4) if o.role != "GK"]
    req = formation_request("4-3-3", 50_000_000, owned_ids=tuple(o.player_id for o in no_keeper), max_signings=0,
                            min_minutes=0, alternatives=0, reference_date=REF)
    sol = solve(make_pool(3, 4), req, owned=no_keeper)
    assert sol.team is None
    assert "allow 1 signing" in [s["change"] for s in sol.diagnosis["suggestions"]]


def test_alternatives_change_the_signings():
    owned = club(5)
    req = formation_request("4-3-3", 30_000_000, owned_ids=tuple(o.player_id for o in owned), max_signings=2,
                            min_minutes=0, alternatives=2, reference_date=REF)
    sol = solve(make_pool(4, 5), req, owned=owned, diagnose_on_failure=False)
    sets = [frozenset(p.player_id for p in t.signings) for t in [sol.team, *sol.alternatives]]
    assert len(sets) == len(set(sets))
    assert all(t.total_score <= sol.team.total_score for t in sol.alternatives)


@pytest.mark.parametrize("seed", range(30))
def test_alternatives_always_differ_in_signings(seed):
    """Strict version: many small cases, every alternative must buy a different set of players."""
    rng = random.Random(seed)
    owned = club(seed)
    req = formation_request(rng.choice(list(FORMATIONS)), rng.choice([2, 10, 40]) * 1_000_000,
                            owned_ids=tuple(o.player_id for o in owned), max_signings=rng.choice([1, 2, 3]),
                            min_minutes=0, alternatives=3, reference_date=REF)
    sol = solve(make_pool(3, seed), req, owned=owned, diagnose_on_failure=False)
    sets = [frozenset(p.player_id for p in t.signings) for t in [sol.team, *sol.alternatives]]
    assert len(sets) == len(set(sets)), sets
    assert all(sets), "an alternative that buys nobody is the current squad, not an alternative"


def test_no_alternatives_when_the_best_plan_buys_nobody():
    owned = club(7)
    req = formation_request("4-3-3", 0, owned_ids=tuple(o.player_id for o in owned), max_signings=2,
                            min_minutes=0, alternatives=2, reference_date=REF)
    sol = solve(make_pool(3, 7), req, owned=owned, diagnose_on_failure=False)
    assert sol.team.signings == [] and sol.alternatives == []


def test_short_squad_gets_the_number_of_signings_it_needs():
    """A squad six starters short with two signings allowed: the fix is six signings, not three."""
    few = [o for o in club(8) if o.role in ("GK", "ST")][:4]
    req = formation_request("4-3-3", 200_000_000, owned_ids=tuple(o.player_id for o in few), max_signings=2,
                            min_minutes=0, alternatives=0, reference_date=REF)
    sol = solve(make_pool(4, 8), req, owned=few)
    assert sol.team is None
    assert "needs 9 more starters" in sol.diagnosis["reason"] and "at most 2 signings are allowed" in sol.diagnosis["reason"]
    assert [s["change"] for s in sol.diagnosis["suggestions"]] == ["allow 9 signings"]


def test_too_many_locked_players_is_explained_and_fixed():
    """Found on real data (FC Barcelona, 2026-11-06): two locked goalkeepers made every plan impossible."""
    owned = club(2)
    gks = sorted([o for o in owned if o.role == "GK"], key=lambda o: o.score)[:2]
    req = formation_request("4-3-3", 100_000_000, owned_ids=tuple(o.player_id for o in owned), max_signings=3,
                            kept_ids=tuple(g.player_id for g in gks), min_minutes=0, alternatives=0, reference_date=REF)
    sol = solve(make_pool(3, 2), req, kept=gks, owned=owned)
    assert sol.team is None
    assert sol.diagnosis["reason"] == "you locked 2 goalkeeper to start, but 4-3-3 has room for 1".replace(
        "goalkeeper to", "goalkeepers to")
    first = sol.diagnosis["suggestions"][0]
    assert first["change"] == f"unlock {gks[0].name}" and first["unlock_ids"] == [gks[0].player_id]


@pytest.mark.parametrize("seed", range(20))
def test_signings_only_for_chosen_positions(seed):
    rng = random.Random(seed)
    owned = club(seed)
    roles = tuple(rng.sample(ROLES, rng.choice([1, 2])))
    req = formation_request("4-3-3", 50_000_000, owned_ids=tuple(o.player_id for o in owned), max_signings=3,
                            signing_roles=roles, min_minutes=0, alternatives=2, reference_date=REF)
    sol = solve(make_pool(4, seed), req, owned=owned, diagnose_on_failure=False)
    for team in [sol.team, *sol.alternatives]:
        assert all(p.role in roles for p in team.signings)
        assert verify(team, req, [], owned) == []
    # it equals the brute force restricted to those positions
    market = [c for c in make_pool(4, seed) if c.role in roles]
    small = sorted(market, key=lambda c: -c.score)[:8]  # keep the brute force small: the best 8 can only help
    assert sol.team.total_score >= brute_force_improve(owned, small, FORMATIONS["4-3-3"], 50_000_000, 3) - 0.05


def test_a_position_that_cannot_be_bought_or_filled_is_explained():
    no_gk = [o for o in club(6) if o.role != "GK"]
    req = formation_request("4-3-3", 50_000_000, owned_ids=tuple(o.player_id for o in no_gk), max_signings=3,
                            signing_roles=("ST",), min_minutes=0, alternatives=0, reference_date=REF)
    sol = solve(make_pool(3, 6), req, owned=no_gk)
    assert sol.team is None
    assert sol.diagnosis["reason"].startswith("your squad has 0 goalkeepers but 4-3-3 needs 1")
    first = sol.diagnosis["suggestions"][0]
    assert first["change"] == "also sign a goalkeeper" and first["add_roles"] == ["GK"]
    assert "allow signings in any position" in [s["change"] for s in sol.diagnosis["suggestions"]]
