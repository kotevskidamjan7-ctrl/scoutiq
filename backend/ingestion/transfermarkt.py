"""Transfermarkt loader: DuckDB snapshot -> PostgreSQL.

Loads, for every ENABLED league in the `league` table:
  1. Clubs that played league games in the chosen seasons.
  2. Players who appeared in those games, or whose current club is in those leagues.
  3. Every historical market valuation for those players (valuation_type = 'transfermarkt').
  4. Transfermarkt season aggregates per player/club/league/season
     (appearances, minutes, goals, assists, cards) as source = 'transfermarkt'.

Safe to re-run: every write is an upsert keyed on the source's own IDs.

Usage (inside the backend container):
    python -m ingestion.transfermarkt                 # seasons 2024 and 2025
    python -m ingestion.transfermarkt --seasons 2024
"""

import argparse
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import pandas as pd
from sqlalchemy import insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models import (
    Club,
    ClubSourceId,
    DataSource,
    ImportRun,
    League,
    MarketValuation,
    Player,
    PlayerSeasonStats,
    PlayerSourceId,
)
from ingestion.normalize import normalize_name, tm_position_group

# Columns this loader relies on, per Transfermarkt table. Checked before anything is written.
REQUIRED_COLUMNS = {
    "clubs": {"club_id", "name"},
    "games": {"game_id", "competition_id", "season", "home_club_id", "away_club_id"},
    "appearances": {
        "player_id", "player_club_id", "game_id", "competition_id",
        "minutes_played", "goals", "assists", "yellow_cards", "red_cards",
    },
    "players": {
        "player_id", "name", "date_of_birth", "country_of_citizenship", "foot", "height_in_cm",
        "position", "sub_position", "current_club_id", "current_club_domestic_competition_id", "last_season",
    },
    "player_valuations": {"player_id", "date", "market_value_in_eur", "current_club_id"},
}

BATCH = 5000


@dataclass
class LoadReport:
    clubs: int = 0
    players_new: int = 0
    players_updated: int = 0
    valuations_inserted: int = 0
    season_stat_rows: int = 0
    players_without_position: int = 0
    players_without_value: int = 0
    latest_valuation_date: str | None = None
    per_league: dict = field(default_factory=dict)

    def print(self) -> None:
        print("\nTransfermarkt load summary")
        print(f"  clubs loaded:              {self.clubs}")
        print(f"  players new / updated:     {self.players_new} / {self.players_updated}")
        print(f"  valuations inserted:       {self.valuations_inserted}")
        print(f"  latest valuation date:     {self.latest_valuation_date}")
        print(f"  season stat rows (TM):     {self.season_stat_rows}")
        print(f"  players without position:  {self.players_without_position}")
        print(f"  players without any value: {self.players_without_value}")
        print("  per league (season: players with league minutes):")
        for league, seasons in sorted(self.per_league.items()):
            print(f"    {league:<6} " + ", ".join(f"{s}: {n}" for s, n in sorted(seasons.items())))


def check_schema(con: duckdb.DuckDBPyConnection) -> None:
    """Fail early, with the real column list, if the snapshot's layout differs from what we expect."""
    problems = []
    for table, needed in REQUIRED_COLUMNS.items():
        try:
            present = {row[0] for row in con.execute(f"DESCRIBE {table}").fetchall()}
        except duckdb.Error:
            problems.append(f"table '{table}' not found")
            continue
        missing = needed - present
        if missing:
            problems.append(f"{table}: missing {sorted(missing)}; has {sorted(present)}")
    if problems:
        raise SystemExit("Transfermarkt snapshot layout not as expected:\n  " + "\n  ".join(problems))


def _none(value):
    """pandas NaN/NaT -> None so it is stored as NULL."""
    return None if pd.isna(value) else value


def _date(value):
    """pandas Timestamp / NaT -> datetime.date / None."""
    value = _none(value)
    return value.date() if hasattr(value, "date") else value


def load(session: Session, con: duckdb.DuckDBPyConnection, seasons: list[int]) -> LoadReport:
    """Run the full load inside `session`. The caller commits (or rolls back in tests)."""
    check_schema(con)
    report = LoadReport()

    source = session.scalar(select(DataSource).where(DataSource.code == "transfermarkt"))
    run = ImportRun(source_id=source.id, kind="tm_snapshot", status="running")
    session.add(run)
    session.flush()

    leagues = session.scalars(
        select(League).where(League.enabled, League.tm_competition_id.is_not(None))
    ).all()
    if not leagues:
        raise SystemExit("No enabled leagues with a Transfermarkt code in the league table.")
    league_by_code = {lg.tm_competition_id: lg for lg in leagues}
    codes = list(league_by_code)
    con.execute("CREATE OR REPLACE TEMP TABLE target_codes AS SELECT unnest(?::VARCHAR[]) AS code", [codes])
    con.execute(
        "CREATE OR REPLACE TEMP TABLE target_seasons AS SELECT unnest(?::INTEGER[]) AS season", [seasons]
    )

    # ---------- 1. clubs ----------
    clubs_df = con.execute(
        """
        WITH league_games AS (
            SELECT g.game_id, g.competition_id, TRY_CAST(g.season AS INTEGER) AS season,
                   g.home_club_id, g.away_club_id
            FROM games g
            WHERE g.competition_id IN (SELECT code FROM target_codes)
              AND TRY_CAST(g.season AS INTEGER) IN (SELECT season FROM target_seasons)
        ),
        club_league AS (
            SELECT home_club_id AS club_id, competition_id, season FROM league_games
            UNION ALL
            SELECT away_club_id, competition_id, season FROM league_games
        ),
        latest AS (  -- a club's league = the one it played in most recently among the chosen seasons
            SELECT club_id, arg_max(competition_id, season) AS competition_id
            FROM club_league GROUP BY club_id
        )
        SELECT c.club_id, c.name, l.competition_id
        FROM latest l JOIN clubs c USING (club_id)
        """
    ).df()

    existing_clubs = dict(
        session.execute(
            select(ClubSourceId.external_id, ClubSourceId.club_id).where(ClubSourceId.source_id == source.id)
        ).all()
    )
    club_map: dict[int, int] = {}  # Transfermarkt club_id -> ScoutIQ club.id
    for row in clubs_df.itertuples(index=False):
        league = league_by_code[row.competition_id]
        ext = str(int(row.club_id))
        if ext in existing_clubs:
            club_id = existing_clubs[ext]
            session.execute(
                update(Club).where(Club.id == club_id).values(name=row.name, league_id=league.id, country=league.country)
            )
        else:
            club = Club(name=row.name, league_id=league.id, country=league.country)
            session.add(club)
            session.flush()
            session.add(ClubSourceId(source_id=source.id, external_id=ext, club_id=club.id))
            club_id = club.id
        club_map[int(row.club_id)] = club_id
    session.flush()
    report.clubs = len(club_map)

    # ---------- 2. players ----------
    players_df = con.execute(
        """
        WITH appeared AS (
            SELECT DISTINCT a.player_id
            FROM appearances a JOIN games g USING (game_id)
            WHERE a.competition_id IN (SELECT code FROM target_codes)
              AND TRY_CAST(g.season AS INTEGER) IN (SELECT season FROM target_seasons)
        ),
        current_in_league AS (
            SELECT player_id FROM players
            WHERE current_club_domestic_competition_id IN (SELECT code FROM target_codes)
              AND TRY_CAST(last_season AS INTEGER) >= (SELECT min(season) FROM target_seasons)
        )
        SELECT p.player_id, p.name, TRY_CAST(p.date_of_birth AS DATE) AS date_of_birth,
               p.country_of_citizenship, p.foot, TRY_CAST(p.height_in_cm AS INTEGER) AS height_in_cm,
               p.position, p.sub_position
        FROM players p
        WHERE p.player_id IN (SELECT player_id FROM appeared UNION SELECT player_id FROM current_in_league)
        """
    ).df()

    existing_players = dict(
        session.execute(
            select(PlayerSourceId.external_id, PlayerSourceId.player_id).where(PlayerSourceId.source_id == source.id)
        ).all()
    )
    player_map: dict[int, int] = {}  # Transfermarkt player_id -> ScoutIQ player.id
    new_rows, new_ext, updates = [], [], []
    for row in players_df.itertuples(index=False):
        group = tm_position_group(_none(row.position))
        if group is None:
            report.players_without_position += 1
        values = {
            "full_name": row.name,
            "name_normalized": normalize_name(row.name),
            "birth_date": _date(row.date_of_birth),
            "nationality": _none(row.country_of_citizenship),
            "foot": _none(row.foot),
            "height_cm": int(row.height_in_cm) if _none(row.height_in_cm) is not None else None,
            "position_group": group,
            "primary_position": _none(row.sub_position),
        }
        ext = str(int(row.player_id))
        if ext in existing_players:
            updates.append({"id": existing_players[ext], **values})
            player_map[int(row.player_id)] = existing_players[ext]
        else:
            new_rows.append(values)
            new_ext.append(int(row.player_id))

    for start in range(0, len(new_rows), BATCH):
        chunk = new_rows[start : start + BATCH]
        ids = session.scalars(
            insert(Player).returning(Player.id, sort_by_parameter_order=True), chunk
        ).all()
        links = []
        for tm_id, player_id in zip(new_ext[start : start + BATCH], ids, strict=True):
            player_map[tm_id] = player_id
            links.append(
                {"source_id": source.id, "external_id": str(tm_id), "player_id": player_id,
                 "match_method": "source_primary", "match_confidence": 1.0}
            )
        session.execute(insert(PlayerSourceId), links)
    for start in range(0, len(updates), BATCH):
        session.execute(update(Player), updates[start : start + BATCH])
    report.players_new, report.players_updated = len(new_rows), len(updates)

    # ---------- 3. valuations ----------
    con.execute(
        "CREATE OR REPLACE TEMP TABLE loaded_players AS SELECT unnest(?::BIGINT[]) AS player_id",
        [list(player_map)],
    )
    vals_df = con.execute(
        """
        SELECT v.player_id, TRY_CAST(v.date AS DATE) AS valuation_date,
               TRY_CAST(v.market_value_in_eur AS BIGINT) AS value_eur, v.current_club_id
        FROM player_valuations v
        WHERE v.player_id IN (SELECT player_id FROM loaded_players)
          AND v.market_value_in_eur IS NOT NULL
        """
    ).df()
    rows = [
        {
            "player_id": player_map[int(r.player_id)],
            "value_eur": int(r.value_eur),
            "valuation_date": _date(r.valuation_date),
            "valuation_type": "transfermarkt",
            "source_id": source.id,
            "club_id": club_map.get(int(r.current_club_id)) if _none(r.current_club_id) is not None else None,
        }
        for r in vals_df.itertuples(index=False)
        if _none(r.valuation_date) is not None and _none(r.value_eur) is not None and r.value_eur >= 0
    ]
    for start in range(0, len(rows), BATCH):
        inserted = session.scalars(
            pg_insert(MarketValuation)
            .values(rows[start : start + BATCH])
            .on_conflict_do_nothing(index_elements=["player_id", "valuation_date", "valuation_type", "source_id"])
            .returning(MarketValuation.id)
        ).all()
        report.valuations_inserted += len(inserted)
    valued = {r["player_id"] for r in rows}
    report.players_without_value = sum(1 for pid in player_map.values() if pid not in valued)
    if rows:
        report.latest_valuation_date = str(max(r["valuation_date"] for r in rows))

    # ---------- 4. Transfermarkt season aggregates (league games only) ----------
    agg_df = con.execute(
        """
        SELECT a.player_id, a.player_club_id, a.competition_id, TRY_CAST(g.season AS INTEGER) AS season,
               count(*) AS appearances, sum(a.minutes_played) AS minutes, sum(a.goals) AS goals,
               sum(a.assists) AS assists, sum(a.yellow_cards) AS yellow, sum(a.red_cards) AS red
        FROM appearances a JOIN games g USING (game_id)
        WHERE a.competition_id IN (SELECT code FROM target_codes)
          AND TRY_CAST(g.season AS INTEGER) IN (SELECT season FROM target_seasons)
        GROUP BY ALL
        """
    ).df()
    stat_rows = []
    for r in agg_df.itertuples(index=False):
        player_id = player_map.get(int(r.player_id))
        club_id = club_map.get(int(r.player_club_id))
        if player_id is None or club_id is None:
            continue
        stat_rows.append(
            {
                "player_id": player_id, "club_id": club_id,
                "league_id": league_by_code[r.competition_id].id, "season": int(r.season),
                "source_id": source.id, "import_run_id": run.id,
                "appearances": int(r.appearances), "minutes": int(r.minutes),
                "goals": int(r.goals), "assists": int(r.assists),
                "cards_yellow": int(r.yellow), "cards_red": int(r.red),
            }
        )
        seasons_for_league = report.per_league.setdefault(r.competition_id, {})
        if r.minutes > 0:
            seasons_for_league[int(r.season)] = seasons_for_league.get(int(r.season), 0) + 1
    for start in range(0, len(stat_rows), BATCH):
        stmt = pg_insert(PlayerSeasonStats).values(stat_rows[start : start + BATCH])
        stmt = stmt.on_conflict_do_update(
            index_elements=["player_id", "club_id", "league_id", "season", "source_id"],
            set_={c: stmt.excluded[c] for c in
                  ("import_run_id", "appearances", "minutes", "goals", "assists", "cards_yellow", "cards_red")},
        )
        session.execute(stmt)
    report.season_stat_rows = len(stat_rows)

    run.status = "success"
    run.finished_at = datetime.now(timezone.utc)
    run.rows_written = report.clubs + len(player_map) + report.valuations_inserted + report.season_stat_rows
    run.notes = f"seasons={seasons}; leagues={sorted(codes)}"
    session.flush()
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Load the Transfermarkt snapshot into PostgreSQL.")
    parser.add_argument("--seasons", type=int, nargs="+", default=[2024, 2025],
                        help="Season start years (2024 = 2024/25). Default: 2024 2025")
    parser.add_argument("--duckdb", type=Path, default=Path(get_settings().tm_duckdb_path))
    args = parser.parse_args()

    if not args.duckdb.exists():
        sys.exit(f"Transfermarkt file not found at {args.duckdb}. Is the data folder mounted?")

    con = duckdb.connect(str(args.duckdb), read_only=True)
    with SessionLocal() as session:
        try:
            report = load(session, con, args.seasons)
            session.commit()
        except BaseException:
            session.rollback()
            raise
    con.close()
    report.print()


if __name__ == "__main__":
    main()
