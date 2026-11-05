"""Run the squad optimizer on the real database from the command line.

Examples (inside the backend container):
    python -m app.optimization.cli --formation 4-3-3 --budget 15m
    python -m app.optimization.cli --needs ST=1,CM=1,CB=1 --budget 500k
    python -m app.optimization.cli --needs CM=2,ST=1 --budget 2m --age-max 25
    python -m app.optimization.cli --formation 4-4-2 --squad 22 --budget 120m --max-per-club 3
"""

import argparse
import sys

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import League
from app.optimization.baselines import best_affordable_per_position, greedy_value, random_feasible
from app.optimization.candidates import load_candidates
from app.optimization.diagnose import fmt_eur
from app.optimization.model import FORMATIONS, ROLES, SLOTS, Team, age_on, formation_request, positions_request, squad_request
from app.optimization.solver import solve


def parse_money(text: str) -> int:
    t = text.strip().lower().replace("€", "").replace(",", "")
    mult = 1_000_000 if t.endswith("m") else 1_000 if t.endswith("k") else 1
    return int(float(t.rstrip("mk")) * mult)


def parse_needs(text: str) -> dict[str, int]:
    needs = {}
    for part in text.split(","):
        role, _, n = part.partition("=")
        role = role.strip().upper()
        if role not in ROLES:
            raise SystemExit(f"Unknown role '{role}'. Use: {', '.join(ROLES)}")
        needs[role] = int(n)
    return needs


def place(team: Team, formation: str | None) -> list[tuple[str, object]]:
    """Display order: pitch slots for a formation (left-footed full-back on the left), else by role."""
    if not formation:
        return [(p.role, p) for r in ROLES for p in sorted(team.players, key=lambda p: -p.score) if p.role == r]
    left = {p.player_id for p in team.players if p.role == "FB" and (p.foot or "").lower() == "left"}
    pools = {r: sorted([p for p in team.players if p.role == r],
                       key=lambda p: (p.player_id not in left, -p.score)) for r in ROLES}
    placed, extra = [], []
    for slot, role in SLOTS[formation]:
        placed.append((slot, pools[role].pop(0)))
    for r in ROLES:
        extra += [("SUB", p) for p in pools[r]]
    return placed + extra


def print_team(team: Team, formation, ref_date, title: str) -> None:
    print(f"\n  {title}: total score {team.total_score:.1f}, cost {fmt_eur(team.cost)}")
    for slot, p in place(team, formation):
        age = age_on(p.birth_date, ref_date)
        flag = "  (2024/25 position differs)" if p.position_consistent is False else ""
        print(f"    {slot:<4} {p.name:<28} {p.role}  score {p.score:5.1f}  {fmt_eur(p.price):>8}  "
              f"age {age if age is not None else '?':<3} {p.club[:22]:<22} {p.league}{flag}")


def main() -> None:
    ap = argparse.ArgumentParser(description="ScoutIQ squad optimizer")
    ap.add_argument("--budget", required=True, help="e.g. 500k, 15m, 2500000")
    ap.add_argument("--formation", choices=sorted(FORMATIONS))
    ap.add_argument("--squad", type=int, help="complete squad of this size instead of a starting XI")
    ap.add_argument("--needs", help="exact signings per role, e.g. ST=1,CM=1,CB=1")
    ap.add_argument("--age-min", type=int)
    ap.add_argument("--age-max", type=int)
    ap.add_argument("--leagues", help="comma-separated league names, e.g. 'Serie A,La Liga'")
    ap.add_argument("--max-price")
    ap.add_argument("--min-minutes", type=int, default=900)
    ap.add_argument("--min-minutes-next", type=int, default=900,
                    help="minimum league minutes in 2025/26 (default 900 = still playing regularly; 0 = off)")
    ap.add_argument("--max-per-club", type=int)
    ap.add_argument("--alternatives", type=int, default=2)
    ap.add_argument("--score", choices=["within", "adjusted"], default="within")
    ap.add_argument("--season", type=int, default=2024)
    ap.add_argument("--no-baselines", action="store_true")
    a = ap.parse_args()

    with SessionLocal() as session:
        candidates = load_candidates(session, a.season, a.score)
        league_ids = ()
        if a.leagues:
            names = {n.strip().lower() for n in a.leagues.split(",")}
            league_ids = tuple(i for i, n in session.execute(select(League.id, League.name)).all() if n.lower() in names)
            if len(league_ids) != len(names):
                sys.exit(f"Unknown league in '{a.leagues}'")

    common = dict(age_min=a.age_min, age_max=a.age_max, league_ids=league_ids,
                  max_price=parse_money(a.max_price) if a.max_price else None, min_minutes=a.min_minutes,
                  min_minutes_next=a.min_minutes_next or None, max_per_club=a.max_per_club, alternatives=a.alternatives)
    budget = parse_money(a.budget)
    if a.needs:
        req = positions_request(parse_needs(a.needs), budget, **common)
    elif a.formation and a.squad:
        req = squad_request(a.formation, budget, size=a.squad, **common)
    elif a.formation:
        req = formation_request(a.formation, budget, **common)
    else:
        sys.exit("Give --formation (optionally with --squad) or --needs.")

    sol = solve(candidates, req)
    print(f"\nScoutIQ optimizer: budget {fmt_eur(budget)}, "
          f"{req.formation or 'signings ' + ', '.join(f'{n} {r}' for r, n in req.role_min.items() if n)}"
          f"{' squad of ' + str(req.squad_size) if a.squad else ''}; "
          f"{sol.candidates_considered} eligible players; score: {a.score}-league; "
          + (f"still playing in {a.season + 1}/{str(a.season + 2)[2:]}: >= {a.min_minutes_next} league minutes"
             if a.min_minutes_next else "recent-form filter off"))
    print(f"  status: {sol.status.upper()}  solve time {sol.solve_time_ms:.0f} ms")

    if sol.team is None:
        if sol.violations:
            print("  VERIFIER REJECTED THE SOLUTION:", *sol.violations, sep="\n    ")
        elif sol.diagnosis:
            d = sol.diagnosis
            print(f"  No feasible team: {d['reason']}.")
            for s in d["suggestions"]:
                print(f"    - {s['change']}: best team would score {s['total_score']:.1f} for {fmt_eur(s['cost'])}")
        return

    print_team(sol.team, req.formation if not a.squad else None, req.reference_date, "Best team")
    print(f"  remaining budget: {fmt_eur(sol.remaining_budget)}   verifier: all constraints satisfied")
    if len({p.league_id for p in sol.team.players}) > 1 and a.score == "within":
        print("  note: within-league scores are compared across leagues (no league adjustment applied)")
    print("  market values are Transfermarkt estimates (up to June 2026), not transfer fees")

    for i, alt in enumerate(sol.alternatives, 1):
        changed = sorted({p.name for p in alt.players} - {p.name for p in sol.team.players})
        print(f"\n  Alternative {i}: total {alt.total_score:.1f}, cost {fmt_eur(alt.cost)}; "
              f"differs by: {', '.join(changed)}")

    if not a.no_baselines:
        print("\n  Baselines on the same candidates and constraints:")
        for label, method in (("best affordable per position", best_affordable_per_position),
                              ("greedy value (score per euro)", greedy_value),
                              ("best of 100 random valid teams", random_feasible)):
            t = method(candidates, req)
            if t is None:
                print(f"    {label:<32} no valid team found")
            else:
                gap = sol.team.total_score - t.total_score
                print(f"    {label:<32} total {t.total_score:6.1f}, cost {fmt_eur(t.cost):>8}  "
                      f"(optimizer +{gap:.1f})")


if __name__ == "__main__":
    main()
