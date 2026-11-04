"""Database tests: the schema itself enforces ScoutIQ's data-integrity rules.

Runs against the database in DATABASE_URL after `alembic upgrade head`.
Every test works inside a transaction that is rolled back, so no rows are left behind.
"""

from datetime import date

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.db.session import engine
from app.models import Club, DataSource, League, MarketValuation, Player, PlayerSeasonStats
from sqlalchemy.orm import Session


@pytest.fixture
def db():
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    yield session
    session.close()
    transaction.rollback()
    connection.close()


def _setup(db: Session):
    source = db.scalar(select(DataSource).where(DataSource.code == "api_football"))
    league = db.scalar(select(League).where(League.tm_competition_id == "GB1"))
    club = Club(name="Test FC", league_id=league.id)
    player = Player(full_name="Test Player", name_normalized="test player", birth_date=date(2000, 1, 1))
    db.add_all([club, player])
    db.flush()
    return source, league, club, player


def test_seed_has_five_enabled_v1_leagues(db):
    rows = db.execute(text("SELECT tm_competition_id FROM league WHERE enabled ORDER BY 1")).scalars().all()
    assert rows == ["ES1", "FR1", "GB1", "IT1", "L1"]


def test_missing_stats_are_stored_as_null_not_zero(db):
    source, league, club, player = _setup(db)
    stats = PlayerSeasonStats(
        player_id=player.id, club_id=club.id, league_id=league.id, season=2024, source_id=source.id, minutes=900
    )
    db.add(stats)
    db.flush()
    db.refresh(stats)
    assert stats.minutes == 900
    assert stats.passes_key is None  # not provided stays NULL


def test_same_player_club_league_season_source_cannot_be_stored_twice(db):
    source, league, club, player = _setup(db)
    kwargs = dict(player_id=player.id, club_id=club.id, league_id=league.id, season=2024, source_id=source.id)
    db.add(PlayerSeasonStats(**kwargs))
    db.flush()
    db.add(PlayerSeasonStats(**kwargs))
    with pytest.raises(IntegrityError):
        db.flush()


def test_valuation_type_must_be_known(db):
    _, _, _, player = _setup(db)
    db.add(MarketValuation(player_id=player.id, value_eur=500_000, valuation_date=date(2026, 6, 1), valuation_type="guess"))
    with pytest.raises(IntegrityError):
        db.flush()


def test_valuation_cannot_be_negative(db):
    _, _, _, player = _setup(db)
    db.add(MarketValuation(player_id=player.id, value_eur=-1, valuation_date=date(2026, 6, 1), valuation_type="transfermarkt"))
    with pytest.raises(IntegrityError):
        db.flush()


def test_position_group_must_be_gk_def_mid_or_fwd(db):
    db.add(Player(full_name="X", name_normalized="x", position_group="ST"))
    with pytest.raises(IntegrityError):
        db.flush()
