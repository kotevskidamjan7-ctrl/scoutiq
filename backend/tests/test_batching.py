"""Multi-row inserts must stay under PostgreSQL's 65,535-parameter limit (bug found on real data, 2026-11-06)."""

import pytest
from sqlalchemy import insert, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.db.session import engine
from app.models import Club, DataSource, League, Player, PlayerSeasonStats
from ingestion.batching import PG_MAX_PARAMS, chunks


def test_chunks_respect_the_parameter_limit():
    rows = [{f"c{i}": 0 for i in range(38)} for _ in range(5000)]
    sizes = [len(c) for c in chunks(rows)]
    assert sum(sizes) == 5000
    assert max(sizes) * 38 <= PG_MAX_PARAMS
    assert max(sizes) == 1724


def test_chunks_handle_empty_and_wide_rows():
    assert list(chunks([])) == []
    wide = [{f"c{i}": 0 for i in range(70_000)}]
    assert [len(c) for c in chunks(wide)] == [1]


@pytest.fixture
def db():
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    yield session
    session.close()
    transaction.rollback()
    connection.close()


def test_2000_full_stat_rows_insert_without_error(db):
    """The exact shape that failed: 2,000 API-Football rows of 38 columns in one load."""
    af = db.scalar(select(DataSource).where(DataSource.code == "api_football"))
    league = db.scalar(select(League).where(League.tm_competition_id == "GB1"))
    club = Club(name="Batch FC", league_id=league.id)
    db.add(club)
    db.flush()
    ids = db.scalars(insert(Player).returning(Player.id, sort_by_parameter_order=True),
                     [{"full_name": f"Batch Player {i}", "name_normalized": f"batch player {i}"} for i in range(2000)]).all()
    stat_cols = ["position_reported", "appearances", "lineups", "minutes", "rating", "goals", "assists", "shots_total",
                 "shots_on", "passes_total", "passes_key", "pass_accuracy", "tackles", "blocks", "interceptions",
                 "duels_total", "duels_won", "dribbles_attempts", "dribbles_success", "dribbled_past", "fouls_drawn",
                 "fouls_committed", "cards_yellow", "cards_yellowred", "cards_red", "penalty_won", "penalty_committed",
                 "penalty_scored", "penalty_missed", "penalty_saved", "saves", "goals_conceded"]
    rows = [{"player_id": pid, "club_id": club.id, "league_id": league.id, "season": 2024, "source_id": af.id,
             "import_run_id": None, **{c: None for c in stat_cols}} for pid in ids]
    assert len(rows[0]) == 38 and len(rows) * 38 > PG_MAX_PARAMS   # one statement would fail
    for chunk in chunks(rows):
        db.execute(pg_insert(PlayerSeasonStats).values(chunk))
    stored = db.scalar(select(PlayerSeasonStats.id).where(PlayerSeasonStats.club_id == club.id).limit(1))
    assert stored is not None
    count = len(db.scalars(select(PlayerSeasonStats.id).where(PlayerSeasonStats.club_id == club.id)).all())
    assert count == 2000
