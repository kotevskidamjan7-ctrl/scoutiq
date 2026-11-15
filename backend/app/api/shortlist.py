"""Shortlist: players a user follows, with private notes. Users only see their own."""

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.models import AppUser, MarketValuation, Player, ShortlistEntry
from app.players.clubs import players_out
from app.players.service import all_rows
from app.schemas.shortlist import ShortlistItem, ShortlistUpdate

router = APIRouter(prefix="/shortlist", tags=["shortlist"])

MAX_ENTRIES = 500


def _latest_values(db: Session, ids: set[int]) -> dict[int, int]:
    """Latest Transfermarkt valuation per player."""
    out: dict[int, int] = {}
    if not ids:
        return out
    for pid, value in db.execute(
        select(MarketValuation.player_id, MarketValuation.value_eur)
        .where(MarketValuation.player_id.in_(ids), MarketValuation.valuation_type == "transfermarkt")
        .order_by(MarketValuation.player_id, MarketValuation.valuation_date)
    ):
        out[pid] = value  # ordered by date, so the last one wins
    return out


def _current_price(db: Session, player_id: int) -> int | None:
    row = next((r for r in all_rows(db) if r.player_id == player_id), None)
    if row is not None and row.price_eur:
        return row.price_eur
    return _latest_values(db, {player_id}).get(player_id)


def _items(db: Session, entries: list[ShortlistEntry]) -> list[dict]:
    rows = {r.player_id: r for r in all_rows(db)}
    missing = {e.player_id for e in entries if e.player_id not in rows}
    basic = {p["player_id"]: p for p in players_out(db, missing)} if missing else {}
    values = _latest_values(db, missing)
    out = []
    for e in entries:
        r = rows.get(e.player_id)
        if r is not None:
            d = {"player_id": r.player_id, "name": r.name, "age": r.age, "nationality": r.nationality, "role": r.role,
                 "league_id": r.league_id, "league": r.league, "club": r.club, "score": r.score,
                 "score_adjusted": r.score_adjusted, "value_for_money": r.value_for_money, "reliability": r.reliability,
                 "minutes": r.minutes, "minutes_next": r.minutes_next, "price_eur": r.price_eur}
        else:  # a player without a 2024/25 score: what is known about him
            b = basic.get(e.player_id, {})
            d = {"player_id": e.player_id, "name": b.get("name", ""), "age": b.get("age"), "nationality": None,
                 "role": b.get("role"), "league_id": None, "league": None, "club": None, "score": None,
                 "score_adjusted": None, "value_for_money": None, "reliability": None, "minutes": None,
                 "minutes_next": b.get("minutes_2025_26"), "price_eur": values.get(e.player_id)}
        now, then = d.get("price_eur"), e.value_at_add_eur
        d.update(note=e.note, added_at=e.added_at, value_at_add_eur=then,
                 value_change_pct=round((now - then) / then * 100, 1) if now and then else None)
        out.append(d)
    return out


@router.get("", response_model=list[ShortlistItem])
def list_own(db: Session = Depends(get_db), user: AppUser = Depends(get_current_user)) -> list[dict]:
    entries = list(db.scalars(select(ShortlistEntry).where(ShortlistEntry.user_id == user.id)
                              .order_by(ShortlistEntry.added_at.desc(), ShortlistEntry.id.desc())))
    return _items(db, entries)


@router.put("/{player_id}", response_model=ShortlistItem)
def add_or_update(player_id: int, body: ShortlistUpdate | None = None, response: Response = None,
                  db: Session = Depends(get_db), user: AppUser = Depends(get_current_user)) -> dict:
    """Adds the player (201) or updates his note (200). Adding twice is harmless."""
    if db.get(Player, player_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Player not found")
    e = db.scalar(select(ShortlistEntry).where(ShortlistEntry.user_id == user.id, ShortlistEntry.player_id == player_id))
    if e is None:
        count = len(db.scalars(select(ShortlistEntry.id).where(ShortlistEntry.user_id == user.id)).all())
        if count >= MAX_ENTRIES:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                                detail=f"Your shortlist is full ({MAX_ENTRIES} players). Remove some first.")
        e = ShortlistEntry(user_id=user.id, player_id=player_id, note=(body.note or "") if body else "",
                           value_at_add_eur=_current_price(db, player_id))
        db.add(e)
        response.status_code = status.HTTP_201_CREATED
    elif body is not None and body.note is not None:
        e.note = body.note
    db.commit()
    db.refresh(e)
    return _items(db, [e])[0]


@router.delete("/{player_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove(player_id: int, db: Session = Depends(get_db), user: AppUser = Depends(get_current_user)) -> Response:
    e = db.scalar(select(ShortlistEntry).where(ShortlistEntry.user_id == user.id, ShortlistEntry.player_id == player_id))
    if e is not None:  # removing a player who is not there is harmless
        db.delete(e)
        db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
