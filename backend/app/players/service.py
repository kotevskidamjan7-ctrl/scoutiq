"""Read-only player data for the explorer, the profile and the comparison (FR-05, FR-06, FR-07, FR-21).

Everything here is read from the database as stored: source data (API-Football, Transfermarkt),
calculated scores (model v1.0) and their breakdowns. Nothing is estimated on the fly.
"""

from dataclasses import dataclass
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Club, DataSource, League, MarketValuation, Player, PlayerSeasonStats, ScoringModel, ScoutingScore
from app.optimization.model import age_on
from app.scoring import model_v1 as M
from ingestion.normalize import normalize_name

SCORED_SEASON = 2024   # 2024/25: the season the scores describe
RECENT_SEASON = 2025   # 2025/26: shown as recent form only (Transfermarkt basics)


@dataclass
class Row:
    """One explorer row: a scored player in the league where he played most in the scored season."""
    player_id: int
    name: str
    name_normalized: str
    birth_date: date | None
    age: int | None
    nationality: str | None
    role: str
    league_id: int
    league: str
    club: str
    score: float
    score_adjusted: float | None
    value_for_money: float | None
    reliability: str
    minutes: int
    minutes_next: int
    price_eur: int | None
    valuation_date: str | None
    position_consistent: bool | None


def _sources(db: Session) -> tuple[DataSource, DataSource]:
    af = db.scalar(select(DataSource).where(DataSource.code == "api_football"))
    tm = db.scalar(select(DataSource).where(DataSource.code == "transfermarkt"))
    return af, tm


def _model(db: Session) -> ScoringModel | None:
    return db.scalar(select(ScoringModel).where(ScoringModel.version == M.VERSION))


def leagues(db: Session) -> list[dict]:
    """Enabled leagues and how many scored players each has."""
    model = _model(db)
    counts: dict[int, int] = {}
    if model is not None:
        counts = dict(db.execute(
            select(ScoutingScore.league_id, func.count())
            .where(ScoutingScore.model_id == model.id, ScoutingScore.season == SCORED_SEASON)
            .group_by(ScoutingScore.league_id)
        ).all())
    rows = db.scalars(select(League).where(League.enabled.is_(True)).order_by(League.country, League.name))
    return [{"id": lg.id, "name": lg.name, "country": lg.country, "scored_players": counts.get(lg.id, 0)} for lg in rows]


def all_rows(db: Session, today: date | None = None) -> list[Row]:
    model = _model(db)
    if model is None:
        return []
    af, tm = _sources(db)
    today = today or date.today()
    next_minutes = dict(db.execute(
        select(PlayerSeasonStats.player_id, func.sum(PlayerSeasonStats.minutes))
        .where(PlayerSeasonStats.source_id == tm.id, PlayerSeasonStats.season == RECENT_SEASON)
        .group_by(PlayerSeasonStats.player_id)
    ).all())
    result = db.execute(
        select(ScoutingScore, Player, League.name, PlayerSeasonStats.minutes, Club.name)
        .join(Player, Player.id == ScoutingScore.player_id)
        .join(League, League.id == ScoutingScore.league_id)
        .join(PlayerSeasonStats, (PlayerSeasonStats.player_id == ScoutingScore.player_id)
              & (PlayerSeasonStats.league_id == ScoutingScore.league_id)
              & (PlayerSeasonStats.season == ScoutingScore.season) & (PlayerSeasonStats.source_id == af.id))
        .outerjoin(Club, Club.id == PlayerSeasonStats.club_id)
        .where(ScoutingScore.model_id == model.id, ScoutingScore.season == SCORED_SEASON)
    ).all()
    best: dict[int, Row] = {}
    for sc, p, league_name, minutes, club_name in result:
        b = sc.breakdown or {}
        value = b.get("market_value") or {}
        row = Row(
            player_id=p.id, name=p.full_name, name_normalized=normalize_name(p.full_name),
            birth_date=p.birth_date, age=age_on(p.birth_date, today), nationality=p.nationality,
            role=sc.role, league_id=sc.league_id, league=league_name, club=club_name or "",
            score=round(float(sc.score_within_league), 1),
            score_adjusted=None if sc.score_adjusted is None else round(float(sc.score_adjusted), 1),
            value_for_money=None if sc.value_for_money is None else round(float(sc.value_for_money), 1),
            reliability=sc.reliability, minutes=int(minutes or 0), minutes_next=int(next_minutes.get(p.id) or 0),
            price_eur=int(value["value_eur"]) if value.get("value_eur") else None,
            valuation_date=value.get("valuation_date"),
            position_consistent=(b.get("position_check") or {}).get("consistent"),
        )
        if p.id not in best or row.minutes > best[p.id].minutes:
            best[p.id] = row
    return list(best.values())


SORT_KEYS = {"score", "price_eur", "value_for_money", "age", "minutes", "minutes_next", "name"}


def with_score(rows: list[Row], score: str) -> list[Row]:
    """score='adjusted': use the league-adjusted score, leaving out players who have none (their league has
    no calibrated strength yet), so that every compared number means the same thing."""
    if score != "adjusted":
        return rows
    from dataclasses import replace
    return [replace(r, score=r.score_adjusted) for r in rows if r.score_adjusted is not None]


def search(rows: list[Row], *, q: str | None = None, roles: list[str] | None = None, league_ids: list[int] | None = None,
           age_min: int | None = None, age_max: int | None = None, max_price: int | None = None,
           min_minutes: int = 900, min_minutes_next: int = 0, sort: str = "score", descending: bool = True,
           limit: int = 50, offset: int = 0) -> tuple[int, list[Row]]:
    needle = normalize_name(q) if q else ""
    out = []
    for r in rows:
        if needle and needle not in r.name_normalized:
            continue
        if roles and r.role not in roles:
            continue
        if league_ids and r.league_id not in league_ids:
            continue
        if age_min is not None and (r.age is None or r.age < age_min):
            continue
        if age_max is not None and (r.age is None or r.age > age_max):
            continue
        if max_price is not None and (r.price_eur is None or r.price_eur > max_price):
            continue
        if r.minutes < min_minutes or r.minutes_next < min_minutes_next:
            continue
        out.append(r)
    present = [r for r in out if getattr(r, sort) is not None]
    missing = [r for r in out if getattr(r, sort) is None]   # unknown values always go last
    present.sort(key=lambda r: (getattr(r, sort), -r.player_id if descending else r.player_id), reverse=descending)
    ordered = present + missing
    return len(ordered), ordered[offset:offset + limit]


STAT_FIELDS = ("appearances", "lineups", "minutes", "rating", "goals", "assists", "shots_total", "shots_on",
               "passes_total", "passes_key", "tackles", "interceptions", "blocks", "duels_total", "duels_won",
               "dribbles_attempts", "dribbles_success", "fouls_drawn", "fouls_committed", "cards_yellow", "cards_red",
               "saves", "goals_conceded", "penalty_scored", "penalty_missed")
RECENT_FIELDS = ("appearances", "minutes", "goals", "assists", "cards_yellow", "cards_red")


def profile(db: Session, player_id: int, today: date | None = None) -> dict | None:
    p = db.get(Player, player_id)
    if p is None:
        return None
    today = today or date.today()
    af, tm = _sources(db)
    model = _model(db)

    def club_league(stats: PlayerSeasonStats) -> tuple[str, str]:
        club = db.get(Club, stats.club_id)
        league = db.get(League, stats.league_id)
        return (club.name if club else ""), (league.name if league else "")

    scores = []
    if model is not None:
        for sc in db.scalars(select(ScoutingScore).where(ScoutingScore.player_id == p.id,
                                                         ScoutingScore.model_id == model.id)
                             .order_by(ScoutingScore.season.desc())):
            b = sc.breakdown or {}
            league = db.get(League, sc.league_id)
            metrics = []
            for key, m in (b.get("metrics") or {}).items():
                d = M.METRICS.get(key)
                metrics.append({"key": key, "label": d.label if d else key, "kind": d.kind if d else "per90",
                                "lower_is_better": bool(d and d.lower_is_better), "value": m.get("value"),
                                "percentile": m.get("percentile"), "weight": m.get("weight")})
            metrics.sort(key=lambda m: -(m["weight"] or 0))
            scores.append({
                "season": sc.season, "league_id": sc.league_id, "league": league.name if league else "",
                "role": sc.role, "score": round(sc.score_within_league, 1),
                "score_adjusted": None if sc.score_adjusted is None else round(sc.score_adjusted, 1),
                "value_for_money": None if sc.value_for_money is None else round(sc.value_for_money, 1),
                "value_for_money_note": b.get("value_for_money_note"),
                "reliability": sc.reliability, "minutes": b.get("minutes"),
                "weight_coverage": b.get("weight_coverage"),
                "dropped_metrics": [M.METRICS[k].label if k in M.METRICS else k for k in b.get("dropped") or []],
                "position_check": b.get("position_check"), "metrics": metrics,
            })

    season_stats = []
    for s in db.scalars(select(PlayerSeasonStats).where(PlayerSeasonStats.player_id == p.id,
                                                        PlayerSeasonStats.source_id == af.id)
                        .order_by(PlayerSeasonStats.season.desc(), PlayerSeasonStats.minutes.desc().nulls_last())):
        club, league = club_league(s)
        season_stats.append({"season": s.season, "club": club, "league": league, "source": "API-Football",
                             **{f: getattr(s, f) for f in STAT_FIELDS}})

    recent_rows = []
    for s in db.scalars(select(PlayerSeasonStats).where(PlayerSeasonStats.player_id == p.id,
                                                        PlayerSeasonStats.source_id == tm.id,
                                                        PlayerSeasonStats.season == RECENT_SEASON)
                        .order_by(PlayerSeasonStats.minutes.desc().nulls_last())):
        club, league = club_league(s)
        recent_rows.append({"club": club, "league": league, **{f: getattr(s, f) for f in RECENT_FIELDS}})
    totals = {f: sum(r[f] or 0 for r in recent_rows) for f in RECENT_FIELDS} if recent_rows else None

    history = db.execute(
        select(MarketValuation.valuation_date, MarketValuation.value_eur)
        .where(MarketValuation.player_id == p.id, MarketValuation.valuation_type == "transfermarkt")
        .order_by(MarketValuation.valuation_date)
    ).all()
    latest = history[-1] if history else None

    return {
        "id": p.id, "name": p.full_name, "birth_date": p.birth_date, "age": age_on(p.birth_date, today),
        "nationality": p.nationality, "foot": p.foot, "height_cm": p.height_cm,
        "primary_position": p.primary_position, "secondary_position": p.secondary_position,
        "market_value": None if latest is None else {"value_eur": int(latest[1]), "valuation_date": latest[0],
                                                     "source": "Transfermarkt"},
        "value_history": [{"date": d, "value_eur": int(v)} for d, v in history],
        "scores": scores,
        "season_stats": season_stats,
        "recent_form": {"season": RECENT_SEASON, "source": "Transfermarkt", "rows": recent_rows, "totals": totals},
    }
