"""Load optimizer candidates from the database: scored players with a market value."""

from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Club, DataSource, League, Player, PlayerSeasonStats, ScoringModel, ScoutingScore
from app.optimization.model import Candidate
from app.scoring import model_v1 as M


def load_candidates(session: Session, season: int = 2024, score: str = "within") -> list[Candidate]:
    """One candidate per player (the league where he played most if he appears in two).

    score: "within" = within-league score; "adjusted" = league-adjusted score where available,
    otherwise the player is left out (no unsupported cross-league comparison).
    """
    model = session.scalar(select(ScoringModel).where(ScoringModel.version == M.VERSION))
    if model is None:
        raise SystemExit(f"No scores for model {M.VERSION}. Run `python -m app.scoring.run` first.")
    af = session.scalar(select(DataSource).where(DataSource.code == "api_football"))
    tm = session.scalar(select(DataSource).where(DataSource.code == "transfermarkt"))

    next_minutes = dict(session.execute(
        select(PlayerSeasonStats.player_id, func.sum(PlayerSeasonStats.minutes))
        .where(PlayerSeasonStats.source_id == tm.id, PlayerSeasonStats.season == season + 1)
        .group_by(PlayerSeasonStats.player_id)
    ).all())

    rows = session.execute(
        select(ScoutingScore, Player, League.name, PlayerSeasonStats.club_id, PlayerSeasonStats.minutes, Club.name)
        .join(Player, Player.id == ScoutingScore.player_id)
        .join(League, League.id == ScoutingScore.league_id)
        .join(PlayerSeasonStats, (PlayerSeasonStats.player_id == ScoutingScore.player_id)
              & (PlayerSeasonStats.league_id == ScoutingScore.league_id)
              & (PlayerSeasonStats.season == ScoutingScore.season) & (PlayerSeasonStats.source_id == af.id))
        .outerjoin(Club, Club.id == PlayerSeasonStats.club_id)
        .where(ScoutingScore.model_id == model.id, ScoutingScore.season == season)
    ).all()

    best: dict[int, Candidate] = {}
    for sc, p, league_name, club_id, minutes, club_name in rows:
        value = (sc.breakdown or {}).get("market_value") or {}
        if not value.get("value_eur"):
            continue
        s = sc.score_adjusted if score == "adjusted" else sc.score_within_league
        if s is None:
            continue
        cand = Candidate(
            player_id=p.id, name=p.full_name, role=sc.role, score=float(s), price=int(value["value_eur"]),
            league_id=sc.league_id, league=league_name, club_id=club_id, club=club_name or "",
            nationality=p.nationality, birth_date=p.birth_date, foot=p.foot, minutes=int(minutes or 0),
            minutes_next=int(next_minutes.get(p.id) or 0),
            valuation_date=date.fromisoformat(value["valuation_date"]) if value.get("valuation_date") else None,
            reliability=sc.reliability,
            position_consistent=((sc.breakdown or {}).get("position_check") or {}).get("consistent"),
        )
        if p.id not in best or cand.minutes > best[p.id].minutes:
            best[p.id] = cand
    return list(best.values())
