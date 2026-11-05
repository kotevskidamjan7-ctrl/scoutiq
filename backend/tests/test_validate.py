"""Tests for the validation report and the position check."""

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import engine
from app.models import DataSource, PlayerSeasonStats
from app.scoring import model_v1 as M
from app.scoring.run import run
from app.scoring.validate import print_report, spearman, validate, weight_sensitivity
from tests.test_scoring import _seed_centre_backs


def test_spearman_is_rank_based():
    a = pd.Series(range(10))
    assert spearman(a, a ** 3) == pytest.approx(1.0)     # monotone, not linear -> still 1
    assert spearman(a, -a) == pytest.approx(-1.0)
    assert spearman(a[:5], a[:5]) is None                # too few points to say anything


def test_position_check():
    assert M.position_check("AW", "Forward")["consistent"] is True     # API uses Forward and Attacker
    assert M.position_check("AW", "Midfielder")["consistent"] is True
    assert M.position_check("FB", "Midfielder")["consistent"] is False  # Wieffer-type case
    assert M.position_check("CB", None)["consistent"] is None


def _fake_scores(n=20, metrics=("a", "b", "c")):
    rng = np.random.default_rng(1)
    rows = []
    for i in range(n):
        pct = {m: float(rng.uniform(0, 100)) for m in metrics}
        rows.append({"league_id": 1, "role": "CB",
                     "breakdown": {"metrics": {m: {"percentile": pct[m], "weight": 1 / len(metrics)} for m in metrics}}})
    return pd.DataFrame(rows)


def test_weight_sensitivity_is_high_for_small_perturbations():
    out = weight_sensitivity(_fake_scores(), draws=200, rng=np.random.default_rng(0))
    assert out["weight_sensitivity"]["median"] > 0.9
    assert out["equal_weights"]["median"] == pytest.approx(1.0)  # weights already equal here


@pytest.fixture
def db():
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    yield session
    session.close()
    transaction.rollback()
    connection.close()


def test_validate_end_to_end(db, capsys):
    league = _seed_centre_backs(db)
    tm = db.scalar(select(DataSource).where(DataSource.code == "transfermarkt"))
    # next season: better 2024/25 scorers keep playing more
    for s in db.scalars(select(PlayerSeasonStats).where(PlayerSeasonStats.source_id == tm.id)).all():
        db.add(PlayerSeasonStats(player_id=s.player_id, club_id=s.club_id, league_id=league.id, season=2025,
                                 source_id=tm.id, minutes=s.minutes, goals=0, assists=0))
    db.flush()
    run(db, 2024)
    report = validate(db, 2024, draws=50)
    assert report["players"] == 12
    assert report["weight_sensitivity"]["median"] > 0.8
    assert report["predictive_minutes_next"]["median"] > 0.5
    print_report(report)
    assert "Weight sensitivity" in capsys.readouterr().out
