"""Dashboard numbers (FR-04): what the data covers, how fresh it is, and where value is.

Read-only. Coverage uses the same definition as the scoring run, so the dashboard and the
command-line report always agree.
"""

from collections import Counter
from statistics import median

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import DataSource, ImportRun, League, LeagueAdjustment, MarketValuation
from app.players import service
from app.scoring import model_v1 as M
from app.scoring.run import PROVISIONAL_BELOW, coverage_vs_transfermarkt

ROLES = ["GK", "CB", "FB", "CM", "AW", "ST"]
PICKS_PER_ROLE = 3
MIN_PICK_SCORE = 50.0  # top half of the role in his league: a cheap weak player is not a find


def league_status(scored: int, coverage: float) -> str:
    if scored == 0:
        return "no_data"
    return "complete" if coverage >= PROVISIONAL_BELOW else "provisional"


def value_picks(rows: list[service.Row]) -> dict[str, list[service.Row]]:
    """Best value for money per role among regulars who still played 900+ minutes in 2025/26.

    Only players whose value for money is shown (the role's price model explains enough) and positive
    (an overpriced player is never a "best value" pick, even when he is the least overpriced), who score in
    the top half of their role (50+), whose score is at least medium reliability, and whose league data is
    complete enough to trust. Without the score floor a very cheap, weak player can top the list, because
    his low price predicts an even lower score.
    """
    picks: dict[str, list[service.Row]] = {}
    for role in ROLES:
        pool = [r for r in rows if r.role == role and r.value_for_money is not None and r.value_for_money > 0
                and r.score >= MIN_PICK_SCORE
                and r.reliability in {"high", "medium"}
                and r.minutes_next >= 900 and r.price_eur is not None]
        pool.sort(key=lambda r: (-r.value_for_money, r.player_id))
        picks[role] = pool[:PICKS_PER_ROLE]
    return picks


BUDGET_CAPS = (1_000_000, 3_000_000, 10_000_000)


def budget_picks(rows: list[service.Row], cap: int) -> dict[str, list[service.Row]]:
    """Highest scores per role at or under a price cap. Needs no price model, so it works for every role.

    Same trust rules as the value picks: reliable score, complete league, still playing in 2025/26.
    """
    picks: dict[str, list[service.Row]] = {}
    for role in ROLES:
        pool = [r for r in rows if r.role == role and r.price_eur is not None and r.price_eur <= cap
                and r.reliability in {"high", "medium"} and r.minutes_next >= 900]
        pool.sort(key=lambda r: (-r.score, r.price_eur, r.player_id))
        picks[role] = pool[:PICKS_PER_ROLE]
    return picks


def dashboard(db: Session, max_age: int | None = None) -> dict:
    leagues = db.scalars(select(League).where(League.enabled.is_(True)).order_by(League.id)).all()
    rows = service.all_rows(db)
    coverage = coverage_vs_transfermarkt(db, leagues, service.SCORED_SEASON) if leagues else {}

    by_league: dict[int, list[service.Row]] = {}
    for r in rows:
        by_league.setdefault(r.league_id, []).append(r)
    complete_ids = set()
    league_rows = []
    for lg in leagues:
        lr = by_league.get(lg.id, [])
        regulars = [r for r in lr if r.minutes >= M.REFERENCE_MINUTES]
        prices = [r.price_eur for r in regulars if r.price_eur]
        status = league_status(len(lr), coverage.get(lg.id, 0.0))
        if status == "complete":
            complete_ids.add(lg.id)
        league_rows.append({
            "id": lg.id, "name": lg.name, "country": lg.country, "status": status,
            "coverage": round(coverage.get(lg.id, 0.0), 3), "scored": len(lr), "regulars": len(regulars),
            "median_value_eur": int(median(prices)) if prices else None,
            "roles": dict(Counter(r.role for r in regulars)),
        })

    tm = db.scalar(select(DataSource).where(DataSource.code == "transfermarkt"))
    latest_valuation = db.scalar(select(func.max(MarketValuation.valuation_date))
                                 .where(MarketValuation.source_id == tm.id)) if tm else None
    sources = {s.id: s.name for s in db.scalars(select(DataSource))}
    imports = [
        {"source": sources.get(r.source_id, ""), "kind": r.kind, "status": r.status,
         "finished_at": r.finished_at or r.started_at, "rows_written": r.rows_written, "requests_used": r.requests_used}
        for r in db.scalars(select(ImportRun).order_by(ImportRun.started_at.desc(), ImportRun.id.desc()).limit(8))
    ]

    model = service._model(db)
    adj = None
    if model is not None:
        adj = db.scalar(select(LeagueAdjustment).where(LeagueAdjustment.model_id == model.id,
                                                       LeagueAdjustment.season == service.SCORED_SEASON))
    # league strength for the scored season, from the source the adjustment uses (UEFA first if none yet)
    from app.scoring.league_adjust import STRENGTH, season_strength
    source = ((adj.details if adj else None) or {}).get("strength")
    strength, strength_source = {}, None
    for src in ([source] if source else ["uefa", "clubelo"]):
        method = STRENGTH[src]["method"] if src == "uefa" else None
        found = season_strength(db, [service.SCORED_SEASON], method)
        if found:
            strength = {lid: v for (lid, _), v in found.items()}
            strength_source = {"uefa": "UEFA season points", "clubelo": "mean ClubElo"}[src]
            break
    for lr in league_rows:
        lr["strength"] = round(strength[lr["id"]], 2) if lr["id"] in strength else None
    trusted = [r for r in rows if r.league_id in complete_ids
               and (max_age is None or (r.age is not None and r.age <= max_age))]
    picks = value_picks(trusted)
    # value for money is shown for a role only when its price model explains enough (scoring run, R^2 >= 0.10)
    vfm_shown = {role: any(r.role == role and r.value_for_money is not None for r in rows) for role in ROLES}

    return {
        "season": service.SCORED_SEASON,
        "max_age": max_age,
        "recent_season": service.RECENT_SEASON,
        "totals": {
            "players_scored": len(rows),
            "regulars_scored": sum(1 for r in rows if r.minutes >= M.REFERENCE_MINUTES),
            "still_playing": sum(1 for r in rows if r.minutes_next >= 900),
            "leagues_complete": len(complete_ids),
            "leagues_enabled": len(leagues),
            "latest_valuation_date": latest_valuation,
        },
        "leagues": league_rows,
        "imports": imports,
        "strength_source": strength_source,
        "model": {
            "version": M.VERSION if model else None,
            "league_adjustment": None if adj is None else {
            "accepted": adj.accepted, "reason": adj.reason,
            "source": {"uefa": "UEFA association coefficients", "clubelo": "ClubElo"}.get(
                (adj.details or {}).get("strength", "clubelo"))},
        },
        "value_picks": {role: [vars(r) for r in picks[role]] for role in ROLES},
        "value_for_money_shown": vfm_shown,
        "budget_picks": {str(cap): {role: [vars(r) for r in rs] for role, rs in budget_picks(trusted, cap).items()}
                         for cap in BUDGET_CAPS},
    }
