"""A club's current squad from API-Football (players/squads), matched to ScoutIQ players.

The Transfermarkt snapshot stops in June 2026, so squads there miss the summer 2026 transfers.
API-Football's squad endpoint has no season and returns the squad as it is now, also on the free plan
(1 request per club). Responses are cached per ISO week, so a club costs at most one request a week.

Matching, in order:
  1. the API-Football player id, already linked to the player when his 2024/25 statistics were loaded;
  2. name and age: exact normalized name, or initial + surname ("I. Meslier" -> "Illan Meslier"),
     age within one year, and only when exactly one player fits.
Players who match nobody (e.g. arrivals from leagues outside the data) are listed by name.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import ClubSourceId, DataSource, Player, PlayerSourceId
from app.optimization.model import age_on
from app.players import clubs
from ingestion.normalize import normalize_name


class SquadUnavailable(Exception):
    """The current squad cannot be fetched now; the message says why, in plain words."""

    def __init__(self, message: str, status: int):
        super().__init__(message)
        self.status = status


def _cache_dir(today: date) -> Path:
    year, week, _ = today.isocalendar()
    return Path(get_settings().raw_dir) / "api_football" / "squads" / f"{year}-W{week:02d}"


def fetch(api_team_id: str, today: date) -> list[dict]:
    """The squad as API-Football returns it: [{id, name, age, number, position}]."""
    from ingestion.api_football_client import (ApiFootballClient, BudgetExhausted, PlanRestricted,
                                               ServerUnavailable)
    settings = get_settings()
    if not settings.api_football_key:
        raise SquadUnavailable("The API-Football key is not set in .env, so current squads cannot be fetched.", 503)
    client = ApiFootballClient(settings.api_football_key, _cache_dir(today), max_requests=1, min_interval_s=0)
    try:
        body = client.get("players/squads", {"team": api_team_id})
    except BudgetExhausted:
        raise SquadUnavailable("Today's API-Football requests are used up. Try again after 01:00.", 429)
    except PlanRestricted as e:
        raise SquadUnavailable(f"API-Football refused the request: {e}", 502)
    except ServerUnavailable:
        raise SquadUnavailable("The API-Football server is having problems. Try again later.", 502)
    except Exception as e:  # network errors and the like: never a 500 for the user
        raise SquadUnavailable(f"Could not reach API-Football ({type(e).__name__}). Try again later.", 502)
    if body.get("errors"):
        raise SquadUnavailable(f"API-Football refused the request: {body['errors']}", 502)
    response = body.get("response") or []
    return response[0].get("players", []) if response else []


def _by_name(db: Session, name: str, age: int | None, today: date) -> int | None:
    norm = normalize_name(name)
    tokens = norm.split()
    if not tokens:
        return None
    if len(tokens) >= 2 and len(tokens[0]) == 1:  # "I. Meslier": initial + surname
        surname = " ".join(tokens[1:])
        rows = db.execute(select(Player.id, Player.name_normalized, Player.birth_date)
                          .where(Player.name_normalized.like(f"%{surname}"))).all()
        rows = [r for r in rows if r.name_normalized.startswith(tokens[0])
                and (r.name_normalized == f"{tokens[0]} {surname}" or r.name_normalized.endswith(f" {surname}"))]
    else:
        rows = db.execute(select(Player.id, Player.name_normalized, Player.birth_date)
                          .where(Player.name_normalized == norm)).all()
    if age is not None:
        rows = [r for r in rows if r.birth_date is None or abs(age_on(r.birth_date, today) - age) <= 1]
    return rows[0].id if len(rows) == 1 else None


def match(db: Session, api_players: list[dict], today: date) -> tuple[dict[int, int], list[dict], int]:
    """Returns ({api id: player id}, unmatched api players, how many matched by name)."""
    af = db.scalar(select(DataSource).where(DataSource.code == "api_football"))
    ids = [str(p["id"]) for p in api_players if p.get("id") is not None]
    linked = dict(db.execute(select(PlayerSourceId.external_id, PlayerSourceId.player_id)
                             .where(PlayerSourceId.source_id == af.id, PlayerSourceId.external_id.in_(ids))).all()) if ids else {}
    out, unmatched, by_name = {}, [], 0
    for p in api_players:
        pid = linked.get(str(p.get("id")))
        if pid is None:
            pid = _by_name(db, p.get("name") or "", p.get("age"), today)
            by_name += pid is not None
        if pid is None:
            unmatched.append({"name": p.get("name") or "", "age": p.get("age"), "position": p.get("position")})
        elif pid not in out.values():
            out[p["id"]] = pid
    return out, unmatched, by_name


def current_squad(db: Session, club_id: int, today: date | None = None, fetcher=None) -> dict | None:
    """The club's squad now: matched players (with scores), who joined and left vs the data, and the unknown."""
    today = today or date.today()
    old = clubs.squad(db, club_id, today)
    if old is None:
        return None
    af = db.scalar(select(DataSource).where(DataSource.code == "api_football"))
    team = db.scalar(select(ClubSourceId.external_id).where(ClubSourceId.source_id == af.id,
                                                            ClubSourceId.club_id == club_id))
    if team is None:
        raise SquadUnavailable(f"{old['club']['name']} is not linked to an API-Football team, so its current squad "
                               "cannot be fetched.", 404)
    api_players = (fetcher or fetch)(team, today)
    if not api_players:
        raise SquadUnavailable("API-Football returned an empty squad for this club.", 502)
    matched, unmatched, by_name = match(db, api_players, today)
    now_ids = set(matched.values())
    old_ids = {p["player_id"] for p in old["players"]}
    return {
        "club": old["club"],
        "fetched": today,
        "players": clubs.players_out(db, now_ids, today),
        "joined_ids": sorted(now_ids - old_ids),
        "left_ids": sorted(old_ids - now_ids),
        "not_in_data": unmatched,
        "matched_by_name": by_name,
    }
