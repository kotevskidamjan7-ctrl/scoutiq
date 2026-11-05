"""POST /api/v1/optimize/squad: Mode A squad optimization (FR-10, FR-12, FR-13, FR-14). Requires login."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models import AppUser
from app.optimization.candidates import load_candidates
from app.optimization.model import Team, age_on, formation_request, positions_request, squad_request
from app.optimization.present import place
from app.optimization.solver import solve
from app.schemas.optimize import Diagnosis, OptimizeRequest, OptimizeResponse, PlayerOut, Suggestion, TeamOut

router = APIRouter(prefix="/optimize", tags=["optimize"])


def _team_out(team: Team, formation: str | None, ref) -> TeamOut:
    return TeamOut(
        total_score=team.total_score,
        cost_eur=team.cost,
        players=[
            PlayerOut(slot=slot, player_id=p.player_id, name=p.name, role=p.role, score=p.score, price_eur=p.price,
                      valuation_date=p.valuation_date.isoformat() if p.valuation_date else None,
                      age=age_on(p.birth_date, ref), club_2024_25=p.club, league=p.league,
                      minutes_2024_25=p.minutes, minutes_2025_26=p.minutes_next, reliability=p.reliability,
                      position_consistent=p.position_consistent)
            for slot, p in place(team, formation)
        ],
    )


@router.post("/squad", response_model=OptimizeResponse)
def optimize_squad(body: OptimizeRequest, db: Session = Depends(get_db),
                   user: AppUser = Depends(get_current_user)) -> OptimizeResponse:
    return run_optimization(body, db)


def run_optimization(body: OptimizeRequest, db: Session) -> OptimizeResponse:
    """The whole Mode A run; shared by the endpoint and by saved scenarios."""
    candidates = load_candidates(db, 2024, body.score)
    common = dict(age_min=body.age_min, age_max=body.age_max, league_ids=tuple(body.league_ids),
                  nationalities=tuple(body.nationalities), exclude_nationalities=tuple(body.exclude_nationalities),
                  max_price=body.max_price_eur, min_minutes=body.min_minutes,
                  min_minutes_next=body.min_minutes_next or None, max_per_club=body.max_per_club,
                  alternatives=body.alternatives)
    if body.needs:
        req = positions_request(dict(body.needs), body.budget_eur, **common)
    elif body.squad_size:
        req = squad_request(body.formation, body.budget_eur, size=body.squad_size, **common)
    else:
        req = formation_request(body.formation, body.budget_eur, **common)

    sol = solve(candidates, req)
    pitch = req.formation if not body.squad_size else None
    notes = ["Market values are Transfermarkt estimates (up to June 2026), not transfer fees or proof of availability.",
             "Scores are from the 2024/25 season; clubs shown are the 2024/25 clubs."]
    if body.min_minutes_next:
        notes.append(f"Only players with at least {body.min_minutes_next} league minutes in 2025/26 were considered.")
    if sol.team and body.score == "within" and len({p.league_id for p in sol.team.players}) > 1:
        notes.append("Within-league scores are compared across leagues; no league-strength adjustment was applied.")

    d = sol.diagnosis
    return OptimizeResponse(
        status=sol.status,
        budget_eur=body.budget_eur,
        remaining_budget_eur=sol.remaining_budget,
        solve_time_ms=sol.solve_time_ms,
        eligible_players=sol.candidates_considered,
        team=_team_out(sol.team, pitch, req.reference_date) if sol.team else None,
        alternatives=[_team_out(t, pitch, req.reference_date) for t in sol.alternatives],
        diagnosis=None if d is None else Diagnosis(
            reason=d["reason"], cheapest_cost_eur=d["cheapest_cost"], budget_shortfall_eur=d["budget_shortfall"],
            suggestions=[Suggestion(change=s["change"], total_score=s["total_score"], cost_eur=s["cost"])
                         for s in d["suggestions"]]),
        notes=notes,
    )
