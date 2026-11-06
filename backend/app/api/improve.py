"""Club improvement (Mode B, FR-11): the best signings for an existing squad. Login required."""

from collections import Counter

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.optimize import _team_out
from app.db.session import get_db
from app.optimization.candidates import load_candidates
from app.optimization.model import FORMATIONS, Team, formation_request
from app.optimization.solver import solve
from app.players import clubs
from app.schemas.optimize import (
    ClubOut,
    Diagnosis,
    ImprovePlayerOut,
    ImproveRequest,
    ImproveResponse,
    ImproveTeamOut,
    SquadNote,
    SquadOut,
    SquadPlayerOut,
    Suggestion,
)

router = APIRouter(tags=["improve"], dependencies=[Depends(get_current_user)])


@router.get("/clubs", response_model=list[ClubOut])
def list_clubs(q: str | None = Query(None, max_length=60), db: Session = Depends(get_db)) -> list[dict]:
    """Clubs in the supported leagues whose name contains q."""
    return clubs.search_clubs(db, q)


@router.get("/clubs/{club_id}/squad", response_model=SquadOut)
def club_squad(club_id: int, db: Session = Depends(get_db)) -> dict:
    """The club's players by the latest season data (2025/26 club, else 2024/25), with 2024/25 scores."""
    out = clubs.squad(db, club_id)
    if out is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Club not found")
    return out


@router.get("/squad/players", response_model=list[SquadPlayerOut])
def squad_players(ids: list[int] = Query(..., max_length=60), db: Session = Depends(get_db)) -> list[dict]:
    """Squad rows for any players, e.g. a signing made after the data was collected."""
    return clubs.players_out(db, set(ids))


def _improve_team(team: Team, owned_ids: set[int], formation: str | None, ref) -> ImproveTeamOut:
    base = _team_out(team, formation, ref)
    return ImproveTeamOut(total_score=base.total_score, cost_eur=base.cost_eur,
                          players=[ImprovePlayerOut(**p.model_dump(), signing=p.player_id not in owned_ids)
                                   for p in base.players])


@router.post("/optimize/improve", response_model=ImproveResponse)
def improve(body: ImproveRequest, db: Session = Depends(get_db)) -> ImproveResponse:
    market = load_candidates(db, 2024, body.score)
    owned_ids = set(body.owned_player_ids)
    owned = load_candidates(db, 2024, body.score, player_ids=owned_ids, require_value=False)
    scored_ids = {o.player_id for o in owned}
    unscored = [SquadNote(**{k: r[k] for k in ("player_id", "name")})
                for r in clubs.players_out(db, owned_ids - scored_ids)]
    locked = [o for o in owned if o.player_id in set(body.locked_player_ids)]

    common = dict(age_min=body.age_min, age_max=body.age_max, league_ids=tuple(body.league_ids),
                  max_price=body.max_price_eur, min_minutes=body.min_minutes,
                  min_minutes_next=body.min_minutes_next or None, alternatives=body.alternatives,
                  owned_ids=tuple(scored_ids), exclude_ids=tuple(owned_ids | set(body.left_player_ids)),  # gone players are not bought back
                  kept_ids=tuple(o.player_id for o in locked))
    req = formation_request(body.formation, body.budget_eur, max_signings=body.max_signings,
                            signing_roles=tuple(dict.fromkeys(body.signing_roles)), **common)

    # the current squad on its own: the same model with no signings allowed
    need = FORMATIONS[body.formation]
    have = Counter(o.role for o in owned)
    missing = {r: n - have.get(r, 0) for r, n in need.items() if have.get(r, 0) < n}
    current_team = None
    if not missing:
        now = solve([], req.relaxed(budget=0, max_signings=0, alternatives=0), kept=locked, owned=owned,
                    diagnose_on_failure=False)
        current_team = now.team

    sol = solve(market, req, kept=locked, owned=owned)
    ref = req.reference_date
    current = _improve_team(current_team, scored_ids, body.formation, ref) if current_team else None
    team = _improve_team(sol.team, scored_ids, body.formation, ref) if sol.team else None

    notes = ["Your players count as free. Each starts only if no affordable signing is better.",
             "Scores are from 2024/25; the squad is taken from the latest season data and may be out of date.",
             "Market values are Transfermarkt estimates (up to June 2026), not transfer fees or proof of availability."]
    if unscored:
        notes.append(f"{len(unscored)} squad player(s) have no 2024/25 score in the supported leagues and were left out.")
    if missing:
        notes.append("Your current squad cannot fill this formation on its own, so the comparison with your current XI is not shown.")

    d = sol.diagnosis
    return ImproveResponse(
        status=sol.status, budget_eur=body.budget_eur, remaining_budget_eur=sol.remaining_budget,
        solve_time_ms=sol.solve_time_ms, eligible_players=sol.candidates_considered,
        current=current, current_missing=missing, team=team,
        gain=round(sol.team.total_score - current_team.total_score, 1) if sol.team and current_team else None,
        alternatives=[_improve_team(t, scored_ids, body.formation, ref) for t in sol.alternatives],
        diagnosis=None if d is None else Diagnosis(
            reason=d["reason"], cheapest_cost_eur=d["cheapest_cost"], budget_shortfall_eur=d["budget_shortfall"],
            suggestions=[Suggestion(change=s["change"], total_score=s["total_score"], cost_eur=s["cost"],
                                    unlock_ids=s.get("unlock_ids", []), add_roles=s.get("add_roles", []))
                         for s in d["suggestions"]]),
        unscored=unscored, notes=notes,
    )
