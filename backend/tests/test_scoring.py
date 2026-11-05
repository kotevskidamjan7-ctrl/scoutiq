"""Tests for the scoring model v1.0 (methodology, Phase 4).

Numbers in the formula tests are worked out by hand in the comments, so each test
documents one rule from the methodology document.
"""

from datetime import date

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.session import engine
from app.models import Club, DataSource, League, MarketValuation, Player, PlayerSeasonStats, ScoutingScore, StatFieldCoverage
from app.scoring import model_v1 as M
from app.scoring.engine import compute_metric, midrank_percentile, score_group, value_for_money
from app.scoring.run import STAT_COLUMNS, run


def frame(rows: list[dict]) -> pd.DataFrame:
    """Rows with minutes + any stat fields; everything else NULL (NaN)."""
    df = pd.DataFrame(rows)
    for col in STAT_COLUMNS:
        if col not in df:
            df[col] = np.nan
    if "player_id" not in df:
        df["player_id"] = range(1, len(df) + 1)
    return df


# ---------- the model definition ----------

def test_weights_sum_to_one_and_follow_the_rules():
    for role, weights in M.WEIGHTS.items():
        assert sum(weights.values()) == pytest.approx(1.0), role
        assert max(weights.values()) <= 0.55 if role == "GK" else max(weights.values()) <= 0.30
        assert set(weights) <= set(M.METRICS)


def test_all_snapshot_subpositions_are_mapped():
    seen = {"Centre-Back", "Left-Back", "Right-Back", "Centre-Forward", "Left Winger", "Right Winger",
            "Second Striker", "Goalkeeper", "Attacking Midfield", "Central Midfield", "Defensive Midfield",
            "Left Midfield", "Right Midfield"}  # distinct values in the snapshot, checked 2026-11-05
    assert seen == set(M.ROLE_BY_SUBPOSITION)
    assert set(M.ROLE_BY_SUBPOSITION.values()) == set(M.ROLES)


# ---------- formulas ----------

def test_midrank_percentile():
    ref = np.array([1, 2, 3, 4])
    # value 3: 2 below + half of 1 tie = 2.5 / 4
    assert midrank_percentile(np.array([3, 0, 5]), ref).tolist() == [0.625, 0.0, 1.0]


def test_per90_shrinkage_by_hand():
    # A: 9 goals in 900 min, B: 0 in 900 -> pooled mean mu = 9 / 1800 * 90 = 0.45 per 90
    # A: (9 + 5 * 0.45) / (1350 / 90) = 11.25 / 15 = 0.75 ;  B: 2.25 / 15 = 0.15
    df = frame([{"minutes": 900, "goals": 9, "penalty_scored": 0}, {"minutes": 900, "goals": 0, "penalty_scored": 0}])
    v = compute_metric(df, M.METRICS["npg90"], df["minutes"] >= 900)
    assert v.tolist() == pytest.approx([0.75, 0.15])


def test_penalties_are_removed_from_goals():
    df = frame([{"minutes": 900, "goals": 9, "penalty_scored": 9}, {"minutes": 900, "goals": 0, "penalty_scored": 0}])
    v = compute_metric(df, M.METRICS["npg90"], df["minutes"] >= 900)
    assert v.tolist() == pytest.approx([0.0, 0.0])  # all of A's goals were penalties


def test_rate_shrinkage_by_hand():
    # duels: A 50/100, B 30/100 -> league rate 0.4; k = 20
    # A: (50 + 20*0.4) / (100 + 20) = 58/120 ; small sample C: 2/2 -> (2 + 8) / 22 = 0.4545, not 1.0
    df = frame([{"minutes": 900, "duels_won": 50, "duels_total": 100},
                {"minutes": 900, "duels_won": 30, "duels_total": 100},
                {"minutes": 500, "duels_won": 2, "duels_total": 2}])
    v = compute_metric(df, M.METRICS["duel_rate"], df["minutes"] >= 900)
    assert v.tolist() == pytest.approx([58 / 120, 38 / 120, 10 / 22])


# ---------- score_group: rules ----------

def _gk_group(n=10):
    rows = []
    for i in range(n):  # keeper i: more saves, fewer goals conceded, as i grows
        rows.append({"player_id": i + 1, "minutes": 2000, "saves": 50 + 5 * i, "goals_conceded": 40 - 2 * i,
                     "passes_total": 600})
    return rows


def test_better_profile_scores_higher_and_lower_is_better_is_inverted():
    out = score_group(frame(_gk_group()), "GK").scores.set_index("player_id")
    assert out.loc[10, "score"] > out.loc[5, "score"] > out.loc[1, "score"]
    gc = out.loc[10, "breakdown"]["metrics"]["gc90"]
    assert gc["percentile"] > 50  # fewest goals conceded -> high percentile


def test_unrecorded_field_is_dropped_and_weights_rescaled():
    rows = _gk_group()
    for r in rows:
        r.pop("passes_total")  # passes never recorded for any keeper
    res = score_group(frame(rows), "GK")
    assert "pas90" in res.dropped_metrics
    b = res.scores.iloc[0]["breakdown"]
    assert b["weight_coverage"] == pytest.approx(0.85)
    assert sum(m["weight"] for m in b["metrics"].values()) == pytest.approx(1.0, abs=1e-3)


def test_recorded_field_null_means_zero_events():
    rows = _gk_group()
    rows[0]["saves"] = None  # 1 of 10 null -> 90% coverage -> recorded -> read as 0 saves
    res = score_group(frame(rows), "GK")
    assert "save_rate" not in res.dropped_metrics
    assert res.scores.set_index("player_id").loc[1, "score"] == res.scores["score"].min()


def test_minutes_thresholds_and_reliability():
    rows = _gk_group() + [{"player_id": 50, "minutes": 600, "saves": 30, "goals_conceded": 10, "passes_total": 200},
                          {"player_id": 51, "minutes": 300, "saves": 20, "goals_conceded": 1, "passes_total": 100},
                          {"player_id": 52, "minutes": 1000, "saves": 30, "goals_conceded": 20, "passes_total": 300}]
    out = score_group(frame(rows), "GK").scores.set_index("player_id")
    assert 51 not in out.index                        # < 450 minutes: not scored
    assert out.loc[50, "reliability"] == "low"        # 450-899
    assert out.loc[52, "reliability"] == "medium"     # 900-1799
    assert out.loc[1, "reliability"] == "high"        # >= 1800


def test_too_few_regulars_is_skipped():
    res = score_group(frame(_gk_group(n=5)), "GK")
    assert res.skipped_reason and res.scores.empty


def test_scores_are_0_to_100_and_centred():
    out = score_group(frame(_gk_group(n=21)), "GK").scores
    assert out["score"].between(0, 100).all()
    assert out["score"].median() == pytest.approx(50, abs=3)


# ---------- value for money ----------

def test_value_for_money_is_residual_against_price():
    values = np.geomspace(1e5, 5e7, 30)
    df = pd.DataFrame({"score": 10 + 5 * np.log(values), "value_eur": values, "league_id": 1, "minutes": 2000})
    df.loc[3, "score"] += 10   # this player outperforms his price by 10 points
    vfm = value_for_money(df)
    # least squares lets the outlier pull the line up slightly, so his residual is a bit under 10
    assert 8.5 < vfm[3] <= 10
    assert vfm.drop(3).abs().max() < 1.5


def test_value_for_money_needs_a_value():
    df = pd.DataFrame({"score": np.arange(30.0), "value_eur": [np.nan] + list(np.geomspace(1e5, 1e7, 29)),
                       "league_id": 1, "minutes": 2000})
    assert np.isnan(value_for_money(df)[0])


# ---------- end to end against the test database ----------

@pytest.fixture
def db():
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    yield session
    session.close()
    transaction.rollback()
    connection.close()


def _seed_centre_backs(db, n=12):
    af = db.scalar(select(DataSource).where(DataSource.code == "api_football"))
    tm = db.scalar(select(DataSource).where(DataSource.code == "transfermarkt"))
    league = db.scalar(select(League).where(League.tm_competition_id == "GB1"))
    club = Club(name="Test FC", league_id=league.id)
    db.add(club)
    db.flush()
    for i in range(n):
        p = Player(full_name=f"Test Defender {i}", name_normalized=f"test defender {i}", birth_date=date(1995, 1, 1 + i),
                   position_group="DEF", primary_position="Centre-Back")
        db.add(p)
        db.flush()
        stats = dict(minutes=2000 + 50 * i, interceptions=20 + 3 * i, tackles=30 + i, blocks=10 + i, duels_won=80 + 4 * i,
                     duels_total=160, passes_total=1000 + 20 * i, cards_yellow=5, cards_red=0)
        db.add(PlayerSeasonStats(player_id=p.id, club_id=club.id, league_id=league.id, season=2024, source_id=af.id, **stats))
        db.add(PlayerSeasonStats(player_id=p.id, club_id=club.id, league_id=league.id, season=2024, source_id=tm.id,
                                 minutes=stats["minutes"]))
        db.add(MarketValuation(player_id=p.id, value_eur=1_000_000 * (i + 1), valuation_date=date(2026, 6, 1),
                               valuation_type="transfermarkt", source_id=tm.id))
    db.flush()
    return league


def test_run_scores_stores_and_is_repeatable(db):
    league = _seed_centre_backs(db)
    report = run(db, 2024)
    rows = db.scalars(select(ScoutingScore).where(ScoutingScore.league_id == league.id)).all()
    assert len(rows) == 12 and {r.role for r in rows} == {"CB"}
    best = max(rows, key=lambda r: r.score_within_league)
    assert best.breakdown["metrics"]["int90"]["percentile"] > 90
    assert best.breakdown["market_value"]["value_eur"] == 12_000_000
    assert "dp90" in next(g["dropped"] for g in report["groups"] if g["role"] == "CB")  # never recorded
    assert db.scalar(select(func.count()).select_from(StatFieldCoverage)) > 0

    run(db, 2024)  # re-run replaces, never duplicates
    assert db.scalar(select(func.count()).select_from(ScoutingScore).where(ScoutingScore.league_id == league.id)) == 12


def test_changed_weights_require_a_new_version(db, monkeypatch):
    _seed_centre_backs(db)
    run(db, 2024)
    monkeypatch.setitem(M.WEIGHTS, "GK", {"save_rate": 0.60, "gc90": 0.25, "pas90": 0.15})
    with pytest.raises(SystemExit, match="Bump VERSION"):
        run(db, 2024)
