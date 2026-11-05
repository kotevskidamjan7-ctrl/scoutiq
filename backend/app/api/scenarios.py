"""Saved scenarios (FR-15, US-08): save, list, reopen, delete. Users only see their own."""

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.optimize import run_optimization
from app.db.session import get_db
from app.models import AppUser, Scenario, ScenarioPlayer
from app.schemas.optimize import OptimizeRequest, OptimizeResponse
from app.schemas.scenario import ScenarioCreate, ScenarioOut, ScenarioSummary

router = APIRouter(prefix="/scenarios", tags=["scenarios"])

NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Scenario not found")


def _summary(s: Scenario) -> dict:
    result = s.result_summary or {}
    team = result.get("team") or {}
    return {"id": s.id, "name": s.name, "mode": s.mode, "status": result.get("status", "unknown"),
            "total_score": team.get("total_score"), "cost_eur": team.get("cost_eur"),
            "budget_eur": s.constraints.get("budget_eur"), "created_at": s.created_at}


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
    return {**_summary(s), "request": body.request, "result": result}


@router.get("", response_model=list[ScenarioSummary])
def list_own(db: Session = Depends(get_db), user: AppUser = Depends(get_current_user)) -> list[dict]:
    rows = db.scalars(select(Scenario).where(Scenario.user_id == user.id).order_by(Scenario.created_at.desc()))
    return [_summary(s) for s in rows]


@router.get("/{scenario_id}", response_model=ScenarioOut)
def reopen(scenario_id: int, db: Session = Depends(get_db), user: AppUser = Depends(get_current_user)) -> dict:
    s = _own(db, user, scenario_id)
    return {**_summary(s), "request": OptimizeRequest(**s.constraints), "result": OptimizeResponse(**s.result_summary)}


@router.delete("/{scenario_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete(scenario_id: int, db: Session = Depends(get_db), user: AppUser = Depends(get_current_user)) -> Response:
    db.delete(_own(db, user, scenario_id))
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
