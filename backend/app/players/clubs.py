"""Clubs and their current squads, for club improvement (Mode B).

"Current" means the latest season we have: a player belongs to the club where he played the most
league minutes in 2025/26 (Transfermarkt). Players with no 2025/26 league minutes fall back to their
2024/25 club. This is the squad as the data shows it, so the page lets the user edit it.
"""

from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Club, DataSource, League, Player, PlayerSeasonStats
from app.optimization.candidates import load_candidates
from app.optimization.model import age_on
from app.players.service import RECENT_SEASON, SCORED_SEASON


def _current_club(db: Session) -> dict[int, int]:
    """player_id -> club_id of his latest club (most league minutes in the latest season with data)."""
    tm = db.scalar(select(DataSource).where(DataSource.code == "transfermarkt"))
    af = db.scalar(select(DataSource).where(DataSource.code == "api_football"))
    current: dict[int, int] = {}
    for season, source in ((SCORED_SEASON, af.id), (SCORED_SEASON, tm.id), (RECENT_SEASON, tm.id)):
        best: dict[int, tuple[int, int]] = {}
        for pid, club_id, minutes in db.execute(
            select(PlayerSeasonStats.player_id, PlayerSeasonStats.club_id, PlayerSeasonStats.minutes)
            .where(PlayerSeasonStats.season == season, PlayerSeasonStats.source_id == source,
                   PlayerSeasonStats.club_id.is_not(None))
        ):
            m = minutes or 0
            if pid not in best or m > best[pid][1]:
                best[pid] = (club_id, m)
        for pid, (club_id, m) in best.items():
            if season == RECENT_SEASON and m == 0:
                continue  # an empty 2025/26 line says nothing about where he plays
            current[pid] = club_id  # later seasons overwrite earlier ones
    return current


def search_clubs(db: Session, q: str | None, limit: int = 20) -> list[dict]:
    rows = db.execute(
        select(Club.id, Club.name, League.name)
        .join(League, League.id == Club.league_id)
        .where(League.enabled.is_(True), *([Club.name.ilike(f"%{q.strip()}%")] if q and q.strip() else []))
        .order_by(Club.name).limit(limit)
    ).all()
    return [{"id": cid, "name": name, "league": league} for cid, name, league in rows]


def squad(db: Session, club_id: int, today: date | None = None) -> dict | None:
    club = db.get(Club, club_id)
    if club is None:
        return None
    today = today or date.today()
    league = db.get(League, club.league_id) if club.league_id else None
    ids = {pid for pid, cid in _current_club(db).items() if cid == club_id}
    return {"club": {"id": club.id, "name": club.name, "league": league.name if league else ""},
            "players": players_out(db, ids, today)}


def players_out(db: Session, ids: set[int], today: date | None = None) -> list[dict]:
    """Squad rows for a set of players: scored players with their score, the rest marked as not scored."""
    today = today or date.today()
    if not ids:
        return []
    scored = {c.player_id: c for c in load_candidates(db, SCORED_SEASON, "within", player_ids=ids, require_value=False)}
    tm = db.scalar(select(DataSource).where(DataSource.code == "transfermarkt"))
    recent = dict(db.execute(
        select(PlayerSeasonStats.player_id, func.sum(PlayerSeasonStats.minutes))
        .where(PlayerSeasonStats.player_id.in_(ids), PlayerSeasonStats.source_id == tm.id,
               PlayerSeasonStats.season == RECENT_SEASON)
        .group_by(PlayerSeasonStats.player_id)
    ).all())
    out = []
    for p in db.scalars(select(Player).where(Player.id.in_(ids))):
        c = scored.get(p.id)
        out.append({
            "player_id": p.id, "name": p.full_name, "age": age_on(p.birth_date, today),
            "position": p.primary_position, "role": c.role if c else None,
            "score": round(c.score, 1) if c else None, "reliability": c.reliability if c else None,
            "price_eur": (c.price or None) if c else None, "minutes_2025_26": int(recent.get(p.id) or 0),
        })
    # scored players first (best first), then the unscored ones by name
    out.sort(key=lambda r: (r["score"] is None, -(r["score"] or 0), r["name"]))
    return out
