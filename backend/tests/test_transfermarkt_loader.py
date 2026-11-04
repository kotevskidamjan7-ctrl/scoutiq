"""Tests for the Transfermarkt loader and name normalization.

Uses a tiny in-memory DuckDB with the same table layout as the real snapshot.
The rows are obviously synthetic ("Test ..."), exist only inside this test,
and the database transaction is rolled back afterwards.
"""

from datetime import date

import duckdb
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.session import engine
from app.models import Club, MarketValuation, Player, PlayerSeasonStats
from ingestion.normalize import normalize_name, tm_position_group
from ingestion.transfermarkt import check_schema, load


# ---------- normalization ----------

@pytest.mark.parametrize(
    "raw, expected",
    [
        ("Martin Ødegaard", "martin odegaard"),
        ("Luka Modrić", "luka modric"),
        ("Đorđe Petrović", "djordje petrovic"),
        ("Vinícius Júnior", "vinicius junior"),
        ("Kylian  Mbappé-Lottin", "kylian mbappe lottin"),
        ("N'Golo Kanté", "ngolo kante"),
        (None, ""),
    ],
)
def test_normalize_name(raw, expected):
    assert normalize_name(raw) == expected


def test_position_groups():
    assert tm_position_group("Attack") == "FWD"
    assert tm_position_group("Goalkeeper") == "GK"
    assert tm_position_group("Missing") is None


# ---------- fixtures ----------

@pytest.fixture
def db():
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    yield session
    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture
def snapshot():
    con = duckdb.connect(":memory:")
    con.execute("CREATE TABLE clubs (club_id BIGINT, name VARCHAR, domestic_competition_id VARCHAR)")
    con.execute("INSERT INTO clubs VALUES (1, 'Test United', 'GB1'), (2, 'Test City', 'GB1'), (3, 'Test Outside', 'XX1')")
    con.execute(
        "CREATE TABLE games (game_id BIGINT, competition_id VARCHAR, season BIGINT, home_club_id BIGINT, away_club_id BIGINT)"
    )
    con.execute("INSERT INTO games VALUES (100, 'GB1', 2024, 1, 2), (101, 'FAC', 2024, 1, 3), (102, 'GB1', 2019, 1, 2)")
    con.execute(
        """CREATE TABLE appearances (appearance_id VARCHAR, game_id BIGINT, player_id BIGINT, player_club_id BIGINT,
           competition_id VARCHAR, yellow_cards BIGINT, red_cards BIGINT, goals BIGINT, assists BIGINT, minutes_played BIGINT)"""
    )
    con.execute(
        """INSERT INTO appearances VALUES
           ('a1', 100, 10, 1, 'GB1', 1, 0, 2, 0, 90),
           ('a2', 100, 11, 2, 'GB1', 0, 0, 0, 1, 45),
           ('a3', 101, 10, 1, 'FAC', 0, 0, 3, 0, 90),   -- cup game: must not count
           ('a4', 102, 12, 1, 'GB1', 0, 0, 1, 0, 90)    -- 2019 season: not loaded
        """
    )
    con.execute(
        """CREATE TABLE players (player_id BIGINT, name VARCHAR, date_of_birth TIMESTAMP, country_of_citizenship VARCHAR,
           foot VARCHAR, height_in_cm DOUBLE, position VARCHAR, sub_position VARCHAR, current_club_id BIGINT,
           current_club_domestic_competition_id VARCHAR, last_season VARCHAR, market_value_in_eur DOUBLE)"""
    )
    con.execute(
        """INSERT INTO players VALUES
           (10, 'Test Strikér', '2001-05-01', 'Testland', 'right', 183, 'Attack', 'Centre-Forward', 1, 'GB1', '2025', 5000000),
           (11, 'Test Keeper', '1995-01-01', NULL, NULL, NULL, 'Missing', NULL, 2, 'GB1', '2024', NULL),
           (12, 'Test Retired', '1980-01-01', 'Testland', 'left', 175, 'Midfield', 'Central Midfield', 1, 'GB1', '2019', 100000)
        """
    )
    con.execute(
        """CREATE TABLE player_valuations (player_id BIGINT, date TIMESTAMP, market_value_in_eur BIGINT,
           current_club_id BIGINT, player_club_domestic_competition_id VARCHAR)"""
    )
    con.execute(
        """INSERT INTO player_valuations VALUES
           (10, '2025-06-01', 4000000, 1, 'GB1'),
           (10, '2026-06-01', 5000000, 1, 'GB1'),
           (12, '2019-06-01', 100000, 1, 'GB1')
        """
    )
    yield con
    con.close()


# ---------- loader ----------

def test_schema_check_rejects_missing_columns():
    con = duckdb.connect(":memory:")
    con.execute("CREATE TABLE clubs (club_id BIGINT)")
    with pytest.raises(SystemExit, match="missing"):
        check_schema(con)


def test_load_only_league_games_of_chosen_seasons(db, snapshot):
    report = load(db, snapshot, seasons=[2024])

    assert report.clubs == 2  # 'Test Outside' only played a cup game
    assert report.players_new == 2  # the 2019-only player is excluded
    assert report.valuations_inserted == 2

    striker = db.scalar(select(Player).where(Player.name_normalized == "test striker"))
    stats = db.scalar(select(PlayerSeasonStats).where(PlayerSeasonStats.player_id == striker.id))
    assert (stats.minutes, stats.goals, stats.appearances) == (90, 2, 1)  # cup goals not included
    assert stats.passes_key is None  # Transfermarkt does not provide it -> NULL, not 0
    assert striker.position_group == "FWD"
    assert striker.birth_date == date(2001, 5, 1)


def test_missing_values_stay_null(db, snapshot):
    report = load(db, snapshot, seasons=[2024])
    keeper = db.scalar(select(Player).where(Player.name_normalized == "test keeper"))
    assert keeper.position_group is None and keeper.height_cm is None
    assert report.players_without_position == 1
    assert report.players_without_value == 1


def test_reload_is_idempotent(db, snapshot):
    load(db, snapshot, seasons=[2024])
    counts = lambda: (  # noqa: E731
        db.scalar(select(func.count()).select_from(Player)),
        db.scalar(select(func.count()).select_from(Club)),
        db.scalar(select(func.count()).select_from(MarketValuation)),
        db.scalar(select(func.count()).select_from(PlayerSeasonStats)),
    )
    first = counts()
    second_report = load(db, snapshot, seasons=[2024])
    assert counts() == first
    assert second_report.players_new == 0 and second_report.valuations_inserted == 0
