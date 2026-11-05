"""Explain why a request has no feasible team, and which single change would fix it.

Every suggestion is checked by re-solving the model; nothing is guessed.
"""

from collections import Counter

from app.optimization.model import ROLES, Candidate, Request, apply_filters
from app.optimization.solver import solve_once

ROLE_NAMES = {"GK": "goalkeepers", "CB": "centre-backs", "FB": "full-backs", "CM": "central midfielders",
              "AW": "attacking/wide players", "ST": "strikers"}


def fmt_eur(amount: int | float | None) -> str:
    if amount is None:
        return "-"
    if amount >= 1_000_000:
        return f"€{amount / 1_000_000:.1f}m"
    return f"€{amount / 1_000:.0f}k"


def _relaxations(req: Request, cheapest: int | None) -> list[tuple[str, Request]]:
    out = []
    if cheapest is not None and cheapest > req.budget:
        out.append((f"increase the budget to {fmt_eur(cheapest)}", req.relaxed(budget=cheapest)))
    if req.age_min is not None or req.age_max is not None:
        lo = None if req.age_min is None else req.age_min - 2
        hi = None if req.age_max is None else req.age_max + 2
        out.append((f"widen the age range to {lo or 'any'}-{hi or 'any'}", req.relaxed(age_min=lo, age_max=hi)))
    if req.league_ids:
        out.append(("search all supported leagues", req.relaxed(league_ids=())))
    if req.nationalities or req.exclude_nationalities:
        out.append(("remove the nationality filter", req.relaxed(nationalities=(), exclude_nationalities=())))
    if req.max_price is not None:
        out.append(("remove the maximum price per player", req.relaxed(max_price=None)))
    if req.min_minutes > 450:
        out.append(("include low-reliability players (450-899 minutes)", req.relaxed(min_minutes=450)))
    if req.min_minutes_next is not None:
        out.append(("remove the 2025/26 minutes filter", req.relaxed(min_minutes_next=None)))
    if req.max_per_club is not None:
        out.append(("remove the limit per club", req.relaxed(max_per_club=None)))
    return out


def diagnose(candidates: list[Candidate], req: Request, kept: list[Candidate] | None = None) -> dict:
    kept = kept or []
    pool = apply_filters(candidates, req)
    available = Counter(c.role for c in pool) + Counter(k.role for k in kept)

    shortages = [
        {"role": r, "available": available.get(r, 0), "needed": req.role_min.get(r, 0),
         "text": f"only {available.get(r, 0)} eligible {ROLE_NAMES[r]} under your filters; "
                 f"{req.role_min.get(r, 0)} are needed"}
        for r in ROLES if available.get(r, 0) < req.role_min.get(r, 0)
    ]

    cheapest = None
    status, team = solve_once(pool, kept, req, use_budget=False, objective="cost")
    if team is not None:
        cheapest = team.cost

    if shortages:
        reason = "; ".join(s["text"] for s in shortages)
    elif cheapest is not None and cheapest > req.budget:
        reason = (f"the cheapest team that meets your requirements costs {fmt_eur(cheapest)}, "
                  f"{fmt_eur(cheapest - req.budget)} more than your budget of {fmt_eur(req.budget)}")
    elif team is None:
        reason = "the position counts, squad size and club limit cannot all be met by the eligible players"
    else:
        reason = "no team found within the time limit"

    suggestions = []
    for label, relaxed in _relaxations(req, cheapest):
        st, t = solve_once(apply_filters(candidates, relaxed), kept, relaxed)
        if t is not None:
            suggestions.append({"change": label, "total_score": t.total_score, "cost": t.cost})
    return {"reason": reason, "shortages": shortages, "cheapest_cost": cheapest,
            "budget_shortfall": None if cheapest is None or cheapest <= req.budget else cheapest - req.budget,
            "suggestions": suggestions}
