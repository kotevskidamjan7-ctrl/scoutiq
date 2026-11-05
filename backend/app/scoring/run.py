"""Compute scouting scores for one season and store them.

Usage (inside the backend container):
    python -m app.scoring.run                    # season 2024, all enabled leagues, top 5 per role
    python -m app.scoring.run --top 10 --league "Premier League"

Re-running replaces this model version's scores for the season (deterministic).
"""

import argparse
from collections import defaultdict
from datetime import datetime, timezone

import pandas as pd
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models import (
    DataSource,
    League,
    MarketValuation,
    Player,
    PlayerSeasonStats,
    ScoringModel,
    ScoutingScore,
    StatFieldCoverage,
)
from app.scoring import model_v1 as M
from app.scoring.engine import score_group, value_for_money

STAT_COLUMNS = sorted({f for m in M.METRICS.values() for f in m.plus + m.minus + m.attempts_plus + m.attempts_minus})
PROVISIONAL_BELOW = 0.90  # share of Transfermarkt regulars with API stats


def get_model(session: Session) -> ScoringModel:
    definition = M.model_definition()
    model = session.scalar(select(ScoringModel).where(ScoringModel.version == M.VERSION))
    if model is None:
        model = ScoringModel(version=M.VERSION, weights=definition, min_minutes=M.MIN_SCORED_MINUTES,
                             notes="Phase 4 methodology, model v1.0")
        session.add(model)
        session.flush()
    elif model.weights != definition:
        raise SystemExit(f"Model {M.VERSION} is stored with different weights or parameters. "
                         "Bump VERSION in app/scoring/model_v1.py instead of changing a published model.")
    return model


def load_frame(session: Session, leagues: list[League], season: int) -> pd.DataFrame:
    af = session.scalar(select(DataSource).where(DataSource.code == "api_football"))
    cols = [getattr(PlayerSeasonStats, c)
            for c in ["player_id", "league_id", "club_id", "minutes", "position_reported", "rating", *STAT_COLUMNS]]
    rows = session.execute(
        select(*cols, Player.full_name, Player.primary_position, Player.position_group, Player.birth_date)
        .join(Player, Player.id == PlayerSeasonStats.player_id)
        .where(PlayerSeasonStats.source_id == af.id, PlayerSeasonStats.season == season,
               PlayerSeasonStats.league_id.in_([lg.id for lg in leagues]))
    ).all()
    df = pd.DataFrame(rows, columns=["player_id", "league_id", "club_id", "minutes", "position_reported", "rating", *STAT_COLUMNS,
                                     "full_name", "primary_position", "position_group", "birth_date"])
    df["role"] = df["primary_position"].map(M.ROLE_BY_SUBPOSITION)

    # latest Transfermarkt valuation per player
    tm = session.scalar(select(DataSource).where(DataSource.code == "transfermarkt"))
    is_tm = (MarketValuation.valuation_type == "transfermarkt") & (MarketValuation.source_id == tm.id)
    last_date = (
        select(MarketValuation.player_id, func.max(MarketValuation.valuation_date).label("d"))
        .where(is_tm).group_by(MarketValuation.player_id).subquery()
    )
    latest = (
        select(MarketValuation.player_id, MarketValuation.value_eur, MarketValuation.valuation_date)
        .join(last_date, (last_date.c.player_id == MarketValuation.player_id)
              & (last_date.c.d == MarketValuation.valuation_date))
        .where(is_tm)
    )
    vals = pd.DataFrame(session.execute(latest).all(), columns=["player_id", "value_eur", "valuation_date"])
    return df.merge(vals, on="player_id", how="left")


def coverage_vs_transfermarkt(session: Session, leagues: list[League], season: int) -> dict[int, float]:
    """Share of Transfermarkt regulars (>= 900 league minutes) that have an API-Football line."""
    af = session.scalar(select(DataSource).where(DataSource.code == "api_football"))
    tm = session.scalar(select(DataSource).where(DataSource.code == "transfermarkt"))
    tm_min = (
        select(PlayerSeasonStats.player_id, PlayerSeasonStats.league_id, func.sum(PlayerSeasonStats.minutes).label("m"))
        .where(PlayerSeasonStats.source_id == tm.id, PlayerSeasonStats.season == season)
        .group_by(PlayerSeasonStats.player_id, PlayerSeasonStats.league_id).subquery()
    )
    has_af = (
        select(PlayerSeasonStats.id).where(
            PlayerSeasonStats.source_id == af.id, PlayerSeasonStats.season == season,
            PlayerSeasonStats.player_id == tm_min.c.player_id, PlayerSeasonStats.league_id == tm_min.c.league_id,
        ).exists()
    )
    out = {}
    for lg in leagues:
        total, covered = session.execute(
            select(func.count(), func.count().filter(has_af)).select_from(tm_min)
            .where(tm_min.c.league_id == lg.id, tm_min.c.m >= M.REFERENCE_MINUTES)
        ).one()
        out[lg.id] = covered / total if total else 0.0
    return out


def run(session: Session, season: int) -> dict:
    model = get_model(session)
    leagues = session.scalars(select(League).where(League.enabled).order_by(League.id)).all()
    df = load_frame(session, leagues, season)
    report = {"model": M.VERSION, "season": season, "unmapped_role": int(df["role"].isna().sum()),
              "groups": [], "scored": 0, "leagues": {lg.id: lg.name for lg in leagues}}
    report["af_coverage"] = coverage_vs_transfermarkt(session, leagues, season)

    session.execute(delete(ScoutingScore).where(ScoutingScore.model_id == model.id, ScoutingScore.season == season))
    session.execute(delete(StatFieldCoverage).where(StatFieldCoverage.model_id == model.id,
                                                    StatFieldCoverage.season == season))

    scored_frames = []
    for (league_id, role), group in df.dropna(subset=["role"]).groupby(["league_id", "role"]):
        result = score_group(group.reset_index(drop=True), role)
        report["groups"].append({
            "league_id": league_id, "role": role, "reference": result.reference_size,
            "scored": len(result.scores), "dropped": result.dropped_metrics, "skipped": result.skipped_reason,
        })
        for c in result.coverage:
            session.add(StatFieldCoverage(model_id=model.id, league_id=int(league_id), season=season, role=role, **c))
        if len(result.scores):
            scored = result.scores.merge(
                group[["player_id", "full_name", "position_group", "value_eur", "valuation_date", "position_reported"]],
                on="player_id")
            scored["league_id"], scored["role"] = league_id, role
            scored_frames.append(scored)

    if not scored_frames:
        return report
    all_scores = pd.concat(scored_frames, ignore_index=True)
    all_scores["vfm"] = pd.Series(dtype=float)
    for role, part in all_scores.groupby("role"):
        all_scores.loc[part.index, "vfm"] = value_for_money(part)

    now = datetime.now(timezone.utc)
    rows = []
    for r in all_scores.itertuples(index=False):
        breakdown = dict(r.breakdown)
        breakdown["position_check"] = M.position_check(r.role, r.position_reported)
        if pd.notna(r.value_eur):
            breakdown["market_value"] = {"value_eur": int(r.value_eur), "valuation_date": str(r.valuation_date)}
        rows.append({
            "player_id": int(r.player_id), "model_id": model.id, "league_id": int(r.league_id), "season": season,
            "role": r.role, "position_group": r.position_group or "", "score_within_league": float(r.score),
            "score_adjusted": None, "value_for_money": None if pd.isna(r.vfm) else float(r.vfm),
            "reliability": r.reliability, "breakdown": breakdown, "computed_at": now,
        })
    for start in range(0, len(rows), 2000):
        session.execute(ScoutingScore.__table__.insert(), rows[start : start + 2000])
    report["scored"] = len(rows)
    report["position_mismatch"] = sum(1 for r in rows if r["breakdown"]["position_check"]["consistent"] is False)
    report["scores"] = all_scores
    return report


def print_report(report: dict, top: int, league_filter: str | None) -> None:
    names = report["leagues"]
    print(f"\nScouting scores {report['model']}, season {report['season']}/{str(report['season'] + 1)[2:]}")
    print(f"  players scored: {report['scored']}   (no role mapped: {report['unmapped_role']}; "
          f"2024/25 API position differs from role: {report.get('position_mismatch', 0)})")
    print("\n  API-Football coverage of Transfermarkt regulars:")
    for lid, share in report["af_coverage"].items():
        flag = "" if share >= PROVISIONAL_BELOW else "   <- provisional: fetch / gap fill not complete"
        print(f"    {names[lid]:<16} {share:6.1%}{flag}")

    print("\n  Per league and role: scored / regulars; metrics dropped by the coverage rule")
    by_league = defaultdict(list)
    for g in report["groups"]:
        by_league[g["league_id"]].append(g)
    for lid, groups in by_league.items():
        parts = []
        for g in sorted(groups, key=lambda g: M.ROLES.index(g["role"])):
            text = f"{g['role']} {g['scored']}/{g['reference']}"
            if g["skipped"]:
                text += f" (skipped: {g['skipped']})"
            elif g["dropped"]:
                text += f" (dropped {', '.join(g['dropped'])})"
            parts.append(text)
        print(f"    {names[lid]:<16} " + "; ".join(parts))

    scores = report.get("scores")
    if scores is None or not top:
        return
    for lid, lname in names.items():
        if league_filter and lname.lower() != league_filter.lower():
            continue
        part = scores[(scores["league_id"] == lid) & (scores["minutes"] >= M.REFERENCE_MINUTES)]
        if part.empty:
            continue
        print(f"\n  Top {top} per role, {lname} (regulars only)")
        for role in M.ROLES:
            best = part[part["role"] == role].nlargest(top, "score")
            if best.empty:
                continue
            listing = ", ".join(
                f"{r.full_name} {r.score:.0f}" + (f" [VfM {r.vfm:+.0f}]" if pd.notna(r.vfm) else "")
                for r in best.itertuples()
            )
            print(f"    {role}: {listing}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Compute scouting scores")
    parser.add_argument("--season", type=int, default=2024)
    parser.add_argument("--top", type=int, default=5)
    parser.add_argument("--league", type=str, default=None)
    args = parser.parse_args()
    with SessionLocal() as session:
        try:
            report = run(session, args.season)
            session.commit()
        except BaseException:
            session.rollback()
            raise
    print_report(report, args.top, args.league)


if __name__ == "__main__":
    main()
