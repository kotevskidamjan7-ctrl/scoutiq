"""Tests for the ClubElo loader, the league-strength calibration and the value-for-money rule.

The calibration tests use SIMULATED leagues with a known strength difference, so we can
check that the method finds an effect when one exists and refuses when it does not.
The ClubElo CSV sample follows the documented layout (Rank,Club,Country,Level,Elo,From,To);
its values are invented test numbers, not real ratings.
"""

from datetime import date

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import engine
from app.models import League, LeagueAdjustment, LeagueStrength, ScoringModel, ScoutingScore
from app.scoring import league_adjust as LA
from app.scoring.run import run as score_run
from ingestion.clubelo import ClubEloClient, league_means, load, parse_csv, season_dates
from tests.test_scoring import _seed_centre_backs

SAMPLE = """Rank,Club,Country,Level,Elo,From,To
1,Test Reds,ENG,1,2000.5,2024-08-30,2024-09-02
2,Test Blues,ENG,1,1900.5,2024-08-30,2024-09-02
3,Test Whites,ESP,1,1950.0,2024-08-30,2024-09-02
None,Test Reserves,ENG,2,1500.0,2024-08-30,2024-09-02
"""


# ---------- ClubElo parsing ----------

def test_parse_and_league_mean_uses_top_division_only():
    df = parse_csv(SAMPLE)
    mean, n = league_means(df, "ENG")
    assert n == 2 and mean == pytest.approx(1950.5)  # level-2 club excluded


def test_unexpected_layout_stops_loudly():
    with pytest.raises(SystemExit, match="missing"):
        parse_csv("Team,Points\nX,3\n")


def test_season_dates_are_september_to_may():
    d = season_dates(2024)
    assert d[0] == date(2024, 9, 1) and d[-1] == date(2025, 5, 1) and len(d) == 9


class _FakeResp:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        pass


class _FakeSession:
    def __init__(self):
        self.calls = 0

    def get(self, url, timeout):
        self.calls += 1
        return _FakeResp(SAMPLE)


def test_client_downloads_each_date_once(tmp_path):
    fake = _FakeSession()
    client = ClubEloClient(tmp_path, session=fake, sleep=lambda s: None)
    client.on(date(2024, 9, 1))
    client.on(date(2024, 9, 1))
    assert fake.calls == 1


# ---------- calibration on simulated leagues ----------

def simulate(league_gap: float, n_movers: int, seed: int = 7) -> pd.DataFrame:
    """Two leagues; league 1's players are `league_gap` SD better than league 2's.
    Movers go from league 2 to league 1 between the seasons. Output = talent + noise."""
    rng = np.random.default_rng(seed)
    rows, pid = [], 0

    def add(league, season, talent):
        ga90 = max(0.0, 0.4 + 0.15 * (talent + rng.normal(0, 0.5)))
        rows.append({"player_id": pid, "league_id": league, "season": season, "role": "ST",
                     "minutes": 2000, "goals": ga90 * 2000 / 90, "assists": 0})

    for league, mean in ((1, league_gap / 2), (2, -league_gap / 2)):
        for _ in range(60):  # stayers
            pid += 1
            t = rng.normal(mean, 1)
            add(league, 2024, t)
            add(league, 2025, t)
    for _ in range(n_movers):
        pid += 1
        t = rng.normal(-league_gap / 2 + 0.5, 1)  # movers are a bit better than their old league
        add(2, 2024, t)
        add(1, 2025, t)
    return pd.DataFrame(rows)


STRENGTH = {(1, 2024): 1800.0, (1, 2025): 1800.0, (2, 2024): 1600.0, (2, 2025): 1600.0}


def test_finds_a_real_league_effect():
    cal = LA.calibrate(simulate(league_gap=1.0, n_movers=40), STRENGTH, 2024, [1, 2])
    assert cal.accepted, cal.reason
    assert cal.beta < 0 and cal.ci_high < 0
    assert cal.n_movers == 40 and cal.n_stayers == 120
    assert cal.e_ref == pytest.approx(1700)


def test_refuses_when_leagues_are_equal():
    cal = LA.calibrate(simulate(league_gap=0.0, n_movers=40), STRENGTH, 2024, [1, 2])
    assert not cal.accepted and "includes zero" in cal.reason


def test_refuses_with_too_few_movers():
    cal = LA.calibrate(simulate(league_gap=1.0, n_movers=5), STRENGTH, 2024, [1, 2])
    assert not cal.accepted and cal.beta is None and "only 5" in cal.reason


def test_adjusted_score_direction():
    assert LA.adjusted_score(50, 1700, 1700, -0.5) == pytest.approx(50, abs=0.1)  # average league: unchanged
    assert LA.adjusted_score(50, 1800, 1700, -0.5) > 50   # stronger league: raised
    assert LA.adjusted_score(50, 1600, 1700, -0.5) < 50   # weaker league: lowered
    assert LA.adjusted_score(100, 1800, 1700, -0.5) < 100  # no pile-up at 100


# ---------- database: load ClubElo, store calibration, apply ----------

@pytest.fixture
def db():
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    yield session
    session.close()
    transaction.rollback()
    connection.close()


def test_clubelo_load_stores_league_means(db, tmp_path):
    report = load(db, ClubEloClient(tmp_path, session=_FakeSession(), sleep=lambda s: None), [2024])
    gb1 = db.scalar(select(League).where(League.tm_competition_id == "GB1"))
    rows = db.scalars(select(LeagueStrength).where(LeagueStrength.league_id == gb1.id)).all()
    assert len(rows) == 9 and rows[0].mean_club_elo == pytest.approx(1950.5)
    assert LA.season_strength(db, [2024])[(gb1.id, 2024)] == pytest.approx(1950.5)
    assert report.clubs_per_league["Premier League"] == (2, 2)
    assert report.clubs_per_league["Serie A"] == (0, 0)  # reported, not invented


def test_accepted_calibration_is_applied_and_survives_rescoring(db, tmp_path):
    league = _seed_centre_backs(db)
    score_run(db, 2024)
    model = db.scalar(select(ScoringModel))
    db.add(LeagueStrength(league_id=league.id, as_of_date=date(2024, 10, 1), mean_club_elo=1800, method="test"))
    db.add(LeagueAdjustment(model_id=model.id, season=2024, beta=-0.5, ci_low=-0.8, ci_high=-0.2, n_movers=40,
                            n_stayers=200, accepted=True, reason="test", e_ref=1700.0))
    db.flush()
    assert LA.apply(db, model, 2024) == 12
    s = db.scalars(select(ScoutingScore)).all()
    assert all(x.score_adjusted is not None and x.score_adjusted >= x.score_within_league for x in s)

    report = score_run(db, 2024)  # re-scoring re-applies the stored calibration
    assert report["adjusted"] == 12


def test_rejected_calibration_leaves_adjusted_empty(db):
    _seed_centre_backs(db)
    score_run(db, 2024)
    model = db.scalar(select(ScoringModel))
    db.add(LeagueAdjustment(model_id=model.id, season=2024, n_movers=3, n_stayers=50, accepted=False, reason="test"))
    db.flush()
    assert LA.apply(db, model, 2024) == 0
    assert all(x.score_adjusted is None for x in db.scalars(select(ScoutingScore)))


def test_value_for_money_hidden_when_price_explains_little(db):
    from app.scoring import run as R
    _seed_centre_backs(db, n=25)
    report = R.run(db, 2024)
    rows = db.scalars(select(ScoutingScore)).all()
    if report["vfm_r2"]["CB"] < R.MIN_VFM_R2:
        assert all(r.value_for_money is None and "value_for_money_note" in r.breakdown for r in rows)
    else:
        assert all(r.value_for_money is not None for r in rows)
