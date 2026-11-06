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
    if amount >= 1_000:
        return f"€{amount / 1_000:.0f}k"
    return f"€{amount:.0f}"


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
    if req.signing_roles:
        out.append(("allow signings in any position", req.relaxed(signing_roles=())))
    return out


def _more_signings(candidates, req: Request, kept, owned) -> tuple[str, Request] | None:
    """Mode B: allow one more signing, with the budget that signing needs if the current budget is too small."""
    if req.max_signings is None or req.max_signings >= req.squad_size:
        return None
    # at least one more, and at least as many as the squad is short of starters
    have = Counter(c.role for c in [*kept, *owned])
    short = sum(max(0, req.role_min.get(r, 0) - have.get(r, 0)) for r in ROLES)
    n = min(req.squad_size, max(req.max_signings + 1, short))
    relaxed = req.relaxed(max_signings=n)
    label = f"allow {n} signing{'s' if n > 1 else ''}"
    _, cheapest = solve_once(apply_filters(candidates, relaxed), kept, relaxed, use_budget=False,
                             objective="cost", owned=owned)
    if cheapest is None:
        return None
    if cheapest.cost > req.budget:
        return f"{label} and raise the budget to {fmt_eur(cheapest.cost)}", relaxed.relaxed(budget=cheapest.cost)
    return label, relaxed


def diagnose(candidates: list[Candidate], req: Request, kept: list[Candidate] | None = None,
             owned: list[Candidate] | None = None) -> dict:
    kept, owned = kept or [], owned or []
    pool = apply_filters(candidates, req)
    available = Counter(c.role for c in pool) + Counter(k.role for k in kept) + Counter(o.role for o in owned)
    # Mode B: a position that may not be bought and that the squad cannot fill
    blocked = [r for r in ROLES if req.signing_roles and r not in req.signing_roles
               and available.get(r, 0) < req.role_min.get(r, 0)]

    shortages = [
        {"role": r, "available": available.get(r, 0), "needed": req.role_min.get(r, 0),
         "text": f"only {available.get(r, 0)} eligible {ROLE_NAMES[r]} under your filters; "
                 f"{req.role_min.get(r, 0)} are needed"}
        for r in ROLES if available.get(r, 0) < req.role_min.get(r, 0)
    ]

    cheapest = None
    status, team = solve_once(pool, kept, req, use_budget=False, objective="cost", owned=owned)
    if team is not None:
        cheapest = team.cost

    have = Counter(k.role for k in kept) + Counter(o.role for o in owned)
    squad_short = {r: req.role_min.get(r, 0) - have.get(r, 0) for r in ROLES if have.get(r, 0) < req.role_min.get(r, 0)}
    locked_roles = Counter(k.role for k in kept)
    over_locked = {r: n for r, n in locked_roles.items() if n > req.role_max.get(r, 0)}
    if over_locked:
        where = f"{req.formation} has" if req.formation else "the request has"
        reason = "; ".join(
            f"you locked {n} {ROLE_NAMES[r] if n > 1 else ROLE_NAMES[r].rstrip('s')} to start, but {where} room for "
            f"{req.role_max.get(r, 0)}" for r, n in over_locked.items())
    elif blocked:
        def count(n, r):
            return f"{n} {ROLE_NAMES[r] if n != 1 else ROLE_NAMES[r].rstrip('s')}"
        reason = "; ".join(f"your squad has {count(available.get(r, 0), r)} but {req.formation or 'the request'} "
                           f"needs {req.role_min.get(r, 0)}, and this position is not among the positions to sign"
                           for r in blocked)
    elif shortages:
        reason = "; ".join(s["text"] for s in shortages)
    elif owned and req.max_signings is not None and sum(squad_short.values()) > req.max_signings:
        need = ", ".join(f"{n} {ROLE_NAMES[r] if n > 1 else ROLE_NAMES[r].rstrip('s')}" for r, n in squad_short.items())
        reason = (f"your squad needs {sum(squad_short.values())} more starters for this formation ({need}), "
                  f"but at most {req.max_signings} signing{'s are' if req.max_signings != 1 else ' is'} allowed")
    elif cheapest is not None and cheapest > req.budget:
        reason = (f"the cheapest team that meets your requirements costs {fmt_eur(cheapest)}, "
                  f"{fmt_eur(cheapest - req.budget)} more than your budget of {fmt_eur(req.budget)}")
    elif team is None:
        reason = ("the position counts and the other limits cannot all be met "
                  "by your players and the eligible signings")
    else:
        reason = "no team found within the time limit"

    suggestions = []
    options = _relaxations(req, cheapest)
    more = _more_signings(candidates, req, kept, owned)
    if more:
        options.append(more)
    for label, relaxed in options:
        st, t = solve_once(apply_filters(candidates, relaxed), kept, relaxed, owned=owned)
        if t is not None:
            suggestions.append({"change": label, "total_score": t.total_score, "cost": t.cost})
    if blocked:
        # the smallest fix: also sign the positions the squad cannot fill
        relaxed = req.relaxed(signing_roles=tuple(req.signing_roles) + tuple(blocked))
        st, t = solve_once(apply_filters(candidates, relaxed), kept, relaxed, owned=owned)
        if t is not None:
            names = " and ".join(ROLE_NAMES[r].rstrip("s") for r in blocked)
            suggestions.insert(0, {"change": f"also sign a {names}", "total_score": t.total_score, "cost": t.cost,
                                   "add_roles": list(blocked)})
    if over_locked:
        # unlock the weakest locked players of each over-full role (they stay available, just not forced)
        unlock = []
        for r, n in over_locked.items():
            unlock += sorted((k for k in kept if k.role == r), key=lambda k: k.score)[: n - req.role_max.get(r, 0)]
        fewer = [k for k in kept if k not in unlock]
        relaxed = req.relaxed(kept_ids=tuple(k.player_id for k in fewer))
        st, t = solve_once(pool, fewer, relaxed, owned=owned)
        if t is not None:
            names = " and ".join(k.name for k in unlock)
            suggestions.insert(0, {"change": f"unlock {names}", "total_score": t.total_score, "cost": t.cost,
                                   "unlock_ids": [k.player_id for k in unlock]})
    return {"reason": reason, "shortages": shortages, "cheapest_cost": cheapest,
            "budget_shortfall": None if cheapest is None or cheapest <= req.budget else cheapest - req.budget,
            "suggestions": suggestions}
