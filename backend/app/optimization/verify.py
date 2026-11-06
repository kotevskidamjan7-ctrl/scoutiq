"""Independent verifier: re-checks a team against the request using real prices.

Deliberately shares no code with the solver or with model.apply_filters, so a bug in
either cannot hide itself. Returns a list of violations; empty means the team is valid.
"""

from collections import Counter

from app.optimization.model import Candidate, Request, Team


def _age(birth, ref) -> int | None:
    if birth is None:
        return None
    years = ref.year - birth.year
    if (ref.month, ref.day) < (birth.month, birth.day):
        years -= 1
    return years


def verify(team: Team, req: Request, kept: list[Candidate] | None = None,
           owned: list[Candidate] | None = None) -> list[str]:
    problems: list[str] = []
    players = team.players
    locked_ids = {k.player_id for k in (kept or [])}
    kept_ids = locked_ids | {o.player_id for o in (owned or [])}  # already at the club: free, no filters

    ids = [p.player_id for p in players]
    if len(ids) != len(set(ids)):
        problems.append("a player is selected more than once")
    if len(players) != req.squad_size:
        problems.append(f"squad size {len(players)} != {req.squad_size}")

    spent = sum(p.price for p in players if p.player_id not in kept_ids)
    if spent > req.budget:
        problems.append(f"cost {spent} exceeds budget {req.budget}")

    roles = Counter(p.role for p in players)
    for role in set(req.role_min) | set(req.role_max) | set(roles):
        n, lo, hi = roles.get(role, 0), req.role_min.get(role, 0), req.role_max.get(role, 0)
        if not lo <= n <= hi:
            problems.append(f"{role}: {n} players, allowed {lo}-{hi}")

    if req.max_signings is not None:
        bought = sum(1 for p in players if p.player_id not in kept_ids)
        if bought > req.max_signings:
            problems.append(f"{bought} signings, limit {req.max_signings}")

    missing_kept = locked_ids - set(ids)
    if missing_kept:
        problems.append(f"kept players missing: {sorted(missing_kept)}")

    if req.max_per_club is not None:
        for club, n in Counter(p.club_id for p in players if p.club_id is not None).items():
            if n > req.max_per_club:
                problems.append(f"club {club}: {n} players, limit {req.max_per_club}")

    for p in players:
        if p.player_id in kept_ids:
            continue
        who = f"{p.name} ({p.player_id})"
        if p.player_id in set(req.exclude_ids):
            problems.append(f"{who} belongs to the user's own club")
        if not p.price or p.price <= 0:
            problems.append(f"{who} has no market value")
        if p.minutes < req.min_minutes:
            problems.append(f"{who}: {p.minutes} minutes < {req.min_minutes}")
        if req.min_minutes_next is not None and p.minutes_next < req.min_minutes_next:
            problems.append(f"{who}: {p.minutes_next} next-season minutes < {req.min_minutes_next}")
        if req.league_ids and p.league_id not in req.league_ids:
            problems.append(f"{who}: league {p.league_id} not selected")
        if req.nationalities and p.nationality not in req.nationalities:
            problems.append(f"{who}: nationality {p.nationality} not selected")
        if req.exclude_nationalities and p.nationality in req.exclude_nationalities:
            problems.append(f"{who}: nationality {p.nationality} excluded")
        if req.signing_roles and p.role not in req.signing_roles:
            problems.append(f"{who}: bought as {p.role}, only {', '.join(req.signing_roles)} allowed")
        if req.max_price is not None and p.price > req.max_price:
            problems.append(f"{who}: price {p.price} > max {req.max_price}")
        if req.age_min is not None or req.age_max is not None:
            age = _age(p.birth_date, req.reference_date)
            if age is None:
                problems.append(f"{who}: age unknown")
            elif (req.age_min is not None and age < req.age_min) or (req.age_max is not None and age > req.age_max):
                problems.append(f"{who}: age {age} outside {req.age_min}-{req.age_max}")
    return problems
