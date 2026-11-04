"""Tests for parsing, linking and loading API-Football data.

The fixture is an excerpt of a REAL API-Football response (team 33, season 2024,
page 1) captured on 2026-11-04. The Transfermarkt side is set up inside the test
transaction with only the fields the linker needs, and rolled back afterwards.
"""

import json
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import engine
from app.models import Club, DataSource, League, LinkCandidate, Player, PlayerSeasonStats, PlayerSourceId
from ingestion.af_load import is_inconsistent, load_cached, parse_height, parse_page
from ingestion.api_football_client import ApiFootballClient

FIXTURE = Path(__file__).parent / "fixtures" / "af_players_team33_2024_p1_excerpt.json"
PL = 39


@pytest.fixture
def page():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture
def db():
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    yield session
    session.close()
    transaction.rollback()
    connection.close()


# ---------- parsing (real response) ----------

def test_only_domestic_league_entries_are_kept(page):
    entries = {e.name: e for e in parse_page(page, PL)}
    eriksen = entries["C. Eriksen"]
    assert eriksen.stats["minutes"] == 1092  # Premier League only; cup and Europa minutes excluded
    assert eriksen.stats["passes_key"] == 31
    assert eriksen.birth_date == date(1992, 2, 14)


def test_rating_and_height_formats(page):
    entries = {e.name: e for e in parse_page(page, PL)}
    assert entries["C. Eriksen"].stats["rating"] == pytest.approx(6.936363)
    assert entries["Reguilón"].height_cm == 178  # API sent "178 cm"
    assert parse_height("180") == 180 and parse_height(None) is None and parse_height("12") is None


def test_stats_without_minutes_are_flagged(page):
    entries = {e.name: e for e in parse_page(page, PL)}
    assert is_inconsistent(entries["J. Sancho"].stats)  # 0 minutes but 768 passes
    assert not is_inconsistent(entries["C. Eriksen"].stats)
    assert not is_inconsistent(entries["Reguilón"].stats)  # nothing at all: simply absent


# ---------- end-to-end load ----------

def _write_cache(tmp_path, page):
    client = ApiFootballClient("offline", tmp_path)
    teams = {"errors": [], "response": [{"team": {"id": 33, "name": "Manchester United"}}]}
    for endpoint, params, body in [
        ("teams", {"league": PL, "season": 2024}, teams),
        ("players", {"team": 33, "season": 2024, "page": 1}, page),
    ]:
        client.cache_path(endpoint, params).write_text(json.dumps({"body": body}), encoding="utf-8")
    return client


def _tm_player(db, name, dob, club, league, minutes):
    tm = db.scalar(select(DataSource).where(DataSource.code == "transfermarkt"))
    p = Player(full_name=name, name_normalized=name.lower().replace("é", "e"), birth_date=dob)
    db.add(p)
    db.flush()
    db.add(PlayerSeasonStats(player_id=p.id, club_id=club.id, league_id=league.id, season=2024,
                             source_id=tm.id, minutes=minutes))
    return p


def test_load_links_by_birth_date_and_uses_transfermarkt_club(db, tmp_path, page):
    league = db.scalar(select(League).where(League.apifootball_id == PL))
    united = Club(name="Manchester United Football Club", league_id=league.id)
    wolves = Club(name="Wolverhampton Wanderers Football Club", league_id=league.id)
    db.add_all([united, wolves])
    db.flush()
    eriksen = _tm_player(db, "Christian Eriksen", date(1992, 2, 14), united, league, 1100)
    cunha = _tm_player(db, "Matheus Cunha", date(1999, 5, 27), wolves, league, 2620)
    sancho = _tm_player(db, "Jadon Sancho", date(2000, 3, 25), united, league, 0)
    bruno = _tm_player(db, "Bruno Fernandes", date(1994, 9, 8), united, league, 3030)

    report = load_cached(db, _write_cache(tmp_path, page), [league], 2024)

    af = db.scalar(select(DataSource).where(DataSource.code == "api_football"))
    stats = {
        s.player_id: s
        for s in db.scalars(select(PlayerSeasonStats).where(PlayerSeasonStats.source_id == af.id))
    }
    # Cunha is listed under Man United by the API, but played 2024/25 for Wolves
    assert stats[cunha.id].club_id == wolves.id
    assert stats[cunha.id].goals == 15
    assert stats[eriksen.id].club_id == united.id and stats[eriksen.id].minutes == 1092
    assert bruno.id in stats
    # Sancho is linked, but his 0-minute line with stats is rejected
    assert sancho.id not in stats and report.inconsistent >= 1
    # Onana and Reguilón have no Transfermarkt player here -> review queue, not guessed
    review = {c.external_name for c in db.scalars(select(LinkCandidate).where(LinkCandidate.source_id == af.id))}
    assert any("Onana" in n for n in review)
    links = {l.player_id: l for l in db.scalars(select(PlayerSourceId).where(PlayerSourceId.source_id == af.id))}
    assert links[eriksen.id].match_method == "dob_name"


def test_load_is_idempotent(db, tmp_path, page):
    league = db.scalar(select(League).where(League.apifootball_id == PL))
    united = Club(name="Manchester United Football Club", league_id=league.id)
    db.add(united)
    db.flush()
    _tm_player(db, "Christian Eriksen", date(1992, 2, 14), united, league, 1100)
    client = _write_cache(tmp_path, page)

    first = load_cached(db, client, [league], 2024)
    second = load_cached(db, client, [league], 2024)
    assert first.linked_new == 1 and second.linked_new == 0 and second.linked_existing == 1
    assert db.query(LinkCandidate).count() == first.to_review  # review rows not duplicated


# ---------- reconciliation, combining, league-aware linking, gap fill ----------

from ingestion.af_load import STAT_FIELDS, AfEntry, best_dob_match, combine, minutes_agree  # noqa: E402
from ingestion.api_football import gap_fill_targets, search_token  # noqa: E402


def _entry(**stats):
    base = {k: None for k in STAT_FIELDS}
    return AfEntry(af_player_id=1, name="X", full_name="X", lastname="X", birth_date=None, height_cm=None,
                   league_af_id=PL, listed_team_id=stats.pop("team", 1), stats={**base, **stats})


def test_minutes_tolerance_is_relative_or_one_match():
    assert minutes_agree(22, 17)          # tiny counts: within 90 minutes
    assert minutes_agree(2600, 2620)
    assert not minutes_agree(0, 1844)     # Minteh case
    assert not minutes_agree(399, 1042)   # partial season


def test_combine_sums_clubs_and_weights_rating():
    a = _entry(team=1, minutes=900, goals=3, passes_key=None, rating=7.0)
    b = _entry(team=2, minutes=300, goals=1, passes_key=4, rating=6.0)
    total = combine([a, b])
    assert total.stats["minutes"] == 1200 and total.stats["goals"] == 4 and total.stats["passes_key"] == 4
    assert total.stats["rating"] == pytest.approx(6.75)


def test_nickname_linked_only_with_shared_league_season():
    # real near miss from the review queue: scored 83 against Transfermarkt's "Savinho"
    e = AfEntry(af_player_id=9, name="Sávio", full_name="Sávio Moreira de Oliveira", lastname="Moreira de Oliveira",
                birth_date=date(2004, 4, 10), height_cm=None, league_af_id=PL, listed_team_id=50, stats={})
    same_dob = [(101, "savinho")]
    pid, score, how, _ = best_dob_match(e, same_dob, in_league={101})
    assert pid == 101 and how == "dob_league_name"
    pid, _, how, best = best_dob_match(e, same_dob, in_league=set())  # no league evidence -> review
    assert pid is None and best == 101


def test_disagreeing_line_is_held_not_stored(db, tmp_path, page):
    league = db.scalar(select(League).where(League.apifootball_id == PL))
    united = Club(name="Manchester United Football Club", league_id=league.id)
    db.add(united)
    db.flush()
    rashford = _tm_player(db, "Marcus Rashford", date(1997, 10, 31), united, league, 1450)  # whole season
    page = {**page, "response": page["response"] + [{
        "player": {"id": 909, "name": "M. Rashford", "firstname": "Marcus", "lastname": "Rashford",
                   "birth": {"date": "1997-10-31"}, "height": "185"},
        "statistics": [{"team": {"id": 33}, "league": {"id": PL},
                        "games": {"minutes": 983, "appearences": 15}, "goals": {"total": 4}}],
    }]}
    report = load_cached(db, _write_cache(tmp_path, page), [league], 2024)
    af = db.scalar(select(DataSource).where(DataSource.code == "api_football"))
    stored = db.scalars(select(PlayerSeasonStats.player_id).where(PlayerSeasonStats.source_id == af.id)).all()
    assert rashford.id not in stored
    assert any("Rashford" in h for h in report.held)
    targets = gap_fill_targets(db, [league], 2024)
    assert ("Marcus Rashford", PL, 1450, "909") in targets  # known API id -> one cheap request


def test_player_record_replaces_listing_and_sums_clubs(db, tmp_path, page):
    league = db.scalar(select(League).where(League.apifootball_id == PL))
    united = Club(name="Manchester United Football Club", league_id=league.id)
    db.add(united)
    db.flush()
    rashford = _tm_player(db, "Marcus Rashford", date(1997, 10, 31), united, league, 1450)
    client = _write_cache(tmp_path, page)
    record = {"errors": [], "response": [{
        "player": {"id": 909, "name": "M. Rashford", "firstname": "Marcus", "lastname": "Rashford",
                   "birth": {"date": "1997-10-31"}},
        "statistics": [
            {"team": {"id": 33}, "league": {"id": PL}, "games": {"minutes": 983}, "goals": {"total": 4}},
            {"team": {"id": 66}, "league": {"id": PL}, "games": {"minutes": 480}, "goals": {"total": 2}},
            {"team": {"id": 66}, "league": {"id": 2}, "games": {"minutes": 300}, "goals": {"total": 1}},  # Europe
        ],
    }]}
    client.cache_path("players", {"id": 909, "season": 2024}).write_text(json.dumps({"body": record}))
    load_cached(db, client, [league], 2024)
    af = db.scalar(select(DataSource).where(DataSource.code == "api_football"))
    row = db.scalar(select(PlayerSeasonStats).where(PlayerSeasonStats.source_id == af.id,
                                                    PlayerSeasonStats.player_id == rashford.id))
    assert row.minutes == 1463 and row.goals == 6  # both clubs, league only


def test_search_token_uses_longest_name_part():
    assert search_token("Kaoru Mitoma") == "mitoma"
    assert search_token("Martin Ødegaard") == "odegaard"
    assert search_token("Bo Li") is None
