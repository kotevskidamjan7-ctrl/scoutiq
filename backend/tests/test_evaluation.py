"""The evaluation's own building blocks (no database)."""

import math
import random

from app.evaluation.run import _brute_force, spearman, spearman_ci, table
from app.optimization.model import Candidate, positions_request
from app.optimization.solver import UNIT, _score10, solve


def _cands(seed: int, per_role: int = 7) -> list[Candidate]:
    rng = random.Random(seed)
    out, pid = [], 0
    for role in ("GK", "CB", "CM", "ST"):
        for _ in range(per_role):
            pid += 1
            out.append(Candidate(player_id=pid, name=f"P{pid}", role=role, score=round(rng.uniform(20, 99), 1),
                                 price=rng.randrange(100_000, 20_000_000, 1_000), league_id=1, league="L", minutes=2000))
    return out


def test_brute_force_agrees_with_the_optimizer_on_random_problems():
    for seed in range(25):
        pool = _cands(seed)
        needs = {"GK": 1, "CB": 2, "ST": 1} if seed % 2 else {"CM": 2, "ST": 1}
        budget = random.Random(seed).randrange(2_000_000, 40_000_000)
        best, tried = _brute_force(pool, needs, budget)
        sol = solve(pool, positions_request(needs, budget, min_minutes=0, min_minutes_next=0, alternatives=0),
                    diagnose_on_failure=False)
        got = None if sol.team is None else (sum(_score10(p) for p in sol.team.players),
                                             -sum(math.ceil(p.price / UNIT) for p in sol.team.players))
        assert got == best, (seed, got, best)
        assert tried == math.prod(math.comb(sum(c.role == r for c in pool), k) for r, k in needs.items())


def test_brute_force_respects_the_budget_and_reports_infeasible():
    pool = _cands(1)
    best, _ = _brute_force(pool, {"GK": 1, "ST": 1}, 1_000)  # nobody costs EUR 1,000
    assert best is None


def test_spearman_helpers():
    x = list(range(30))
    assert spearman(x, [v * 2 for v in x]) == 1.0
    assert spearman(x, [-v for v in x]) == -1.0
    assert spearman(x[:5], x[:5]) is None          # too few
    rho, lo, hi = spearman_ci(x, [v + (7 if v % 3 == 0 else 0) for v in x])
    assert lo <= rho <= hi and rho > 0.8


def test_markdown_table():
    t = table(["A", "B"], [[1, None], ["x", 2]])
    assert t.splitlines() == ["| A | B |", "|---|---|", "| 1 | – |", "| x | 2 |"]
