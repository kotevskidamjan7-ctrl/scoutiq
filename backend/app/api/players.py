"""Player explorer, profile and comparison (FR-05, FR-06, FR-07, FR-21). Login required."""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.players import dashboard, service
from app.schemas.players import CompareOut, DashboardOut, LeagueOut, PlayerPage, ProfileOut

router = APIRouter(tags=["players"], dependencies=[Depends(get_current_user)])

Role = Literal["GK", "CB", "FB", "CM", "AW", "ST"]
Sort = Literal["score", "price_eur", "value_for_money", "age", "minutes", "minutes_next", "name"]


@router.get("/leagues", response_model=list[LeagueOut])
def list_leagues(db: Session = Depends(get_db)) -> list[dict]:
    """Supported leagues and how many players have a 2024/25 score in each."""
    return service.leagues(db)


@router.get("/players", response_model=PlayerPage)
def search_players(
    q: str | None = Query(None, max_length=60, description="Part of the name; accents are ignored"),
    role: list[Role] = Query([], description="One or more roles"),
    league_id: list[int] = Query([], description="One or more league ids from /leagues"),
    age_min: int | None = Query(None, ge=15, le=45),
    age_max: int | None = Query(None, ge=15, le=45),
    max_price_eur: int | None = Query(None, gt=0),
    min_minutes: int = Query(900, ge=450, le=4000, description="League minutes in 2024/25"),
    min_minutes_next: int = Query(0, ge=0, le=4000, description="League minutes in 2025/26; 0 = no filter"),
    sort: Sort = "score",
    order: Literal["desc", "asc"] = "desc",
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> dict:
    """Scored players (model v1.0, 2024/25), filtered and sorted. Players without a value sort last."""
    if age_min is not None and age_max is not None and age_min > age_max:
        raise HTTPException(status_code=422, detail="age_min is greater than age_max")
    total, items = service.search(
        service.all_rows(db), q=q, roles=role, league_ids=league_id, age_min=age_min, age_max=age_max,
        max_price=max_price_eur, min_minutes=min_minutes, min_minutes_next=min_minutes_next,
        sort=sort, descending=order == "desc", limit=limit, offset=offset)
    return {"total": total, "limit": limit, "offset": offset, "items": [vars(r) for r in items]}


@router.get("/players/compare", response_model=CompareOut)
def compare(ids: list[int] = Query(..., description="2 to 4 player ids"), db: Session = Depends(get_db)) -> dict:
    """Profiles side by side. Scores are only directly comparable when the players share a role."""
    unique = list(dict.fromkeys(ids))
    if not 2 <= len(unique) <= 4:
        raise HTTPException(status_code=422, detail="Choose 2 to 4 different players")
    profiles = [service.profile(db, i) for i in unique]
    if any(p is None for p in profiles):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Player not found")
    roles = {p["scores"][0]["role"] if p["scores"] else None for p in profiles}
    return {"players": profiles, "same_role": len(roles) == 1 and None not in roles}


@router.get("/players/{player_id}", response_model=ProfileOut)
def get_profile(player_id: int, db: Session = Depends(get_db)) -> dict:
    """Identity, market value history, 2024/25 score with its breakdown, season stats and 2025/26 recent form."""
    p = service.profile(db, player_id)
    if p is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Player not found")
    return p


@router.get("/stats/dashboard", response_model=DashboardOut)
def get_dashboard(db: Session = Depends(get_db)) -> dict:
    """Coverage per league, data freshness, recent imports, model status and value-for-money picks."""
    return dashboard.dashboard(db)
