"""Exact squad optimizer: binary integer program solved with OR-Tools CP-SAT.

    Stage 1:  z* = max sum s_i x_i
    Stage 2:  min sum c_i x_i   subject to   sum s_i x_i >= z*
    s.t.      sum c_i x_i <= B                     (budget, signings only)
              L_r <= sum_{i in P_r} x_i <= U_r      (positions)
              sum x_i = N                           (squad size)
              x_i = 1 for kept players              (Mode B)
              sum_{i in club k} x_i <= K            (optional club limit)
              x_i in {0, 1}

Integer coefficients: score x 10 (one decimal); price rounded UP to EUR 1,000 and the budget
rounded DOWN, so a team that fits the integer model always fits the real budget.
"""

import math
import time
from collections import defaultdict

from ortools.sat.python import cp_model

from app.optimization.model import ROLES, Candidate, Request, Solution, Team, apply_filters

UNIT = 1000  # EUR


def _score10(c: Candidate) -> int:
    return int(round(c.score * 10))


def _price_units(c: Candidate, kept: set[int]) -> int:
    return 0 if c.player_id in kept else math.ceil(c.price / UNIT)


def solve_once(pool: list[Candidate], kept: list[Candidate], req: Request,
               cuts: list[set[int]] | None = None, use_budget: bool = True,
               objective: str = "score") -> tuple[str, Team | None]:
    """One two-stage solve. objective='score' (normal) or 'cost' (cheapest feasible team, for diagnosis)."""
    players = list(kept) + [c for c in pool if c.player_id not in {k.player_id for k in kept}]
    kept_ids = {k.player_id for k in kept}
    model = cp_model.CpModel()
    x = {c.player_id: model.new_bool_var(f"x_{c.player_id}") for c in players}
    price = {c.player_id: _price_units(c, kept_ids) for c in players}
    score = {c.player_id: _score10(c) for c in players}

    if use_budget:
        model.add(sum(price[i] * x[i] for i in x) <= req.budget // UNIT)                 # (1)
    by_role = defaultdict(list)
    for c in players:
        by_role[c.role].append(x[c.player_id])
    for r in ROLES:                                                                       # (2)
        total = sum(by_role[r]) if by_role[r] else 0
        model.add(total >= req.role_min.get(r, 0))
        model.add(total <= req.role_max.get(r, 0))
    model.add(sum(x.values()) == req.squad_size)                                          # (3)
    for k in kept_ids:                                                                    # (4)
        model.add(x[k] == 1)
    if req.max_per_club is not None:                                                      # (5)
        by_club = defaultdict(list)
        for c in players:
            if c.club_id is not None:
                by_club[c.club_id].append(x[c.player_id])
        for vars_ in by_club.values():
            model.add(sum(vars_) <= req.max_per_club)
    for cut in cuts or []:                                                                # no-good cuts
        free = [i for i in cut if i not in kept_ids and i in x]
        if free:
            model.add(sum(x[i] for i in free) <= len(free) - 1)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = req.time_limit_s
    solver.parameters.num_workers = 8

    total_score = sum(score[i] * x[i] for i in x)
    total_price = sum(price[i] * x[i] for i in x)
    if objective == "cost":
        model.minimize(total_price)
        status = solver.solve(model)
    else:
        model.maximize(total_score)                                                       # stage 1
        status = solver.solve(model)
        if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            best = int(round(solver.objective_value))
            proven = status == cp_model.OPTIMAL
            model.add(total_score >= best)                                                # stage 2
            model.minimize(total_price)
            status2 = solver.solve(model)
            if status2 in (cp_model.OPTIMAL, cp_model.FEASIBLE):
                status = cp_model.OPTIMAL if (proven and status2 == cp_model.OPTIMAL) else cp_model.FEASIBLE

    if status == cp_model.INFEASIBLE:
        return "infeasible", None
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return "unknown", None  # time limit reached without any solution
    chosen = [c for c in players if solver.value(x[c.player_id])]
    return ("optimal" if status == cp_model.OPTIMAL else "feasible"), Team(chosen, frozenset(kept_ids))


def solve(candidates: list[Candidate], req: Request, kept: list[Candidate] | None = None,
          diagnose_on_failure: bool = True) -> Solution:
    """Full run: filters -> best team -> alternatives -> independent verification -> diagnosis if infeasible."""
    from app.optimization.verify import verify

    kept = kept or []
    start = time.perf_counter()
    pool = apply_filters(candidates, req)
    sol = Solution(status="infeasible", budget=req.budget, candidates_considered=len(pool))
    status, team = solve_once(pool, kept, req)
    if team is not None:
        sol.status, sol.team = status, team
        cuts = [team.ids()]
        for _ in range(req.alternatives):
            st, alt = solve_once(pool, kept, req, cuts=cuts)
            if alt is None:
                break
            sol.alternatives.append(alt)
            cuts.append(alt.ids())
    else:
        sol.status = status
    sol.solve_time_ms = round((time.perf_counter() - start) * 1000, 1)

    if sol.team is not None:
        sol.violations = verify(sol.team, req, kept)
        for alt in sol.alternatives:
            sol.violations += [f"alternative: {v}" for v in verify(alt, req, kept)]
        if sol.violations:
            sol.status, sol.team, sol.alternatives = "error", None, []
    elif diagnose_on_failure:
        from app.optimization.diagnose import diagnose
        sol.diagnosis = diagnose(candidates, req, kept)
    return sol
