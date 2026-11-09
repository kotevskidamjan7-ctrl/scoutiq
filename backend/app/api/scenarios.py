"""Saved scenarios (FR-15, US-08): save, list, reopen, delete. Users only see their own.

Both squad-builder teams (mode "build") and club-improvement plans (mode "improve") are stored.
"""

import re

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.improve import improve as run_improve
from app.api.optimize import run_optimization
from app.db.session import get_db
from app.models import AppUser, Club, League, Scenario, ScenarioPlayer
from app.reports.pdf import scenario_pdf
from app.schemas.optimize import ImproveRequest, ImproveResponse, OptimizeRequest, OptimizeResponse
from app.schemas.scenario import AnyScenarioOut, ImproveScenarioCreate, ImproveScenarioOut, ScenarioCreate, ScenarioOut, ScenarioSummary

router = APIRouter(prefix="/scenarios", tags=["scenarios"])

NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Scenario not found")


def _summary(s: Scenario) -> dict:
    result = s.result_summary or {}
    team = result.get("team") or {}
    out = {"id": s.id, "name": s.name, "mode": s.mode, "status": result.get("status", "unknown"),
           "total_score": team.get("total_score"), "cost_eur": team.get("cost_eur"), "created_at": s.created_at}
    if s.mode == "improve":
        req = s.constraints.get("request") or {}
        current = result.get("current") or {}
        gain = None
        if team and current:
            gain = round(team["total_score"] - current["total_score"], 1)
        return {**out, "budget_eur": req.get("budget_eur", 0), "club_name": s.constraints.get("club_name"),
                "gain": gain, "signings": sum(1 for p in team.get("players", []) if p.get("signing")) if team else None}
    return {**out, "budget_eur": s.constraints.get("budget_eur")}


def _own(db: Session, user: AppUser, scenario_id: int) -> Scenario:
    s = db.get(Scenario, scenario_id)
    if s is None or s.user_id != user.id:
        raise NOT_FOUND  # same answer for "missing" and "not yours": no information leak
    return s


@router.post("", response_model=ScenarioOut, status_code=status.HTTP_201_CREATED)
def save(body: ScenarioCreate, db: Session = Depends(get_db), user: AppUser = Depends(get_current_user)) -> dict:
    """Runs the optimization on the server and stores the request and its result."""
    result = run_optimization(body.request, db)
    s = Scenario(user_id=user.id, name=body.name, mode="build", constraints=body.request.model_dump(mode="json"),
                 result_summary=result.model_dump(mode="json"), solve_time_ms=result.solve_time_ms)
    if result.team:
        s.players = [ScenarioPlayer(player_id=p.player_id, slot=p.slot, is_existing=False) for p in result.team.players]
    db.add(s)
    db.commit()
    db.refresh(s)
    return _out(s)


@router.post("/improve", response_model=ImproveScenarioOut, status_code=status.HTTP_201_CREATED)
def save_improve(body: ImproveScenarioCreate, db: Session = Depends(get_db),
                 user: AppUser = Depends(get_current_user)) -> dict:
    """Runs the club improvement on the server and stores the request, the club and the result."""
    club = db.get(Club, body.club_id) if body.club_id is not None else None
    if body.club_id is not None and club is None:
        raise HTTPException(status_code=422, detail="Unknown club")
    result = run_improve(body.request, db)
    s = Scenario(user_id=user.id, name=body.name, mode="improve",
                 constraints={"club_id": body.club_id, "club_name": club.name if club else None,
                              "request": body.request.model_dump(mode="json")},
                 result_summary=result.model_dump(mode="json"), solve_time_ms=result.solve_time_ms)
    if result.team:
        s.players = [ScenarioPlayer(player_id=p.player_id, slot=p.slot, is_existing=not p.signing)
                     for p in result.team.players]
    db.add(s)
    db.commit()
    db.refresh(s)
    return _out(s)


def _out(s: Scenario) -> dict:
    if s.mode == "improve":
        return {**_summary(s), "club_id": s.constraints.get("club_id"),
                "request": ImproveRequest(**s.constraints["request"]), "result": ImproveResponse(**s.result_summary)}
    return {**_summary(s), "request": OptimizeRequest(**s.constraints), "result": OptimizeResponse(**s.result_summary)}


@router.get("", response_model=list[ScenarioSummary])
def list_own(db: Session = Depends(get_db), user: AppUser = Depends(get_current_user)) -> list[dict]:
    rows = db.scalars(select(Scenario).where(Scenario.user_id == user.id).order_by(Scenario.created_at.desc()))
    return [_summary(s) for s in rows]


@router.get("/{scenario_id}", response_model=AnyScenarioOut)
def reopen(scenario_id: int, db: Session = Depends(get_db), user: AppUser = Depends(get_current_user)) -> dict:
    return _out(_own(db, user, scenario_id))


@router.get("/{scenario_id}/report.pdf", response_class=Response,
            responses={200: {"content": {"application/pdf": {}}, "description": "A one-page PDF report"}})
def report(scenario_id: int, db: Session = Depends(get_db), user: AppUser = Depends(get_current_user)) -> Response:
    """The saved scenario as a one-page A4 PDF: key figures, the XI on a pitch, signings, requirements."""
    s = _out(_own(db, user, scenario_id))
    data = {**s, "request": s["request"].model_dump(mode="json"), "result": s["result"].model_dump(mode="json")}
    ids = data["request"].get("league_ids") or []
    names = {lg.id: lg.name for lg in db.scalars(select(League).where(League.id.in_(ids)))} if ids else {}
    slug = re.sub(r"[^A-Za-z0-9]+", "-", s["name"]).strip("-")[:60] or "scenario"
    return Response(scenario_pdf(data, names), media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="scoutiq-{slug}.pdf"'})


@router.delete("/{scenario_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete(scenario_id: int, db: Session = Depends(get_db), user: AppUser = Depends(get_current_user)) -> Response:
    db.delete(_own(db, user, scenario_id))
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
