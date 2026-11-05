"""Explorer, profile and comparison endpoints (FR-05, FR-06, FR-07, FR-21)."""

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import engine, get_db
from app.main import app
from app.models import Club, DataSource, Player, PlayerSeasonStats
from app.scoring.run import run as score_run
from tests.test_scoring import _seed_centre_backs

PW = "Scout-pass-2026"


@pytest.fixture
def seeded():
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    league = _seed_centre_backs(session, n=12)  # Test Defender 0..11, valued EUR 1m..12m, better ones cost more
    tm = session.scalar(select(DataSource).where(DataSource.code == "transfermarkt"))
    club = session.scalar(select(Club).where(Club.name == "Test FC"))
    players = session.scalars(select(Player).where(Player.full_name.like("Test Defender %")).order_by(Player.id)).all()
    players[3].full_name = "Luka Modrić-Test"            # accents must not matter in search
    players[3].name_normalized = "stale value"  # search must not rely on the stored form
    # 2025/26 recent form for two players; player 0 played for two clubs
    other = Club(name="Second FC", league_id=league.id)
    session.add(other)
    session.flush()
    session.add_all([
        PlayerSeasonStats(player_id=players[0].id, club_id=club.id, league_id=league.id, season=2025, source_id=tm.id,
                          appearances=10, minutes=800, goals=1, assists=0, cards_yellow=2, cards_red=0),
        PlayerSeasonStats(player_id=players[0].id, club_id=other.id, league_id=league.id, season=2025, source_id=tm.id,
                          appearances=12, minutes=1000, goals=0, assists=2, cards_yellow=1, cards_red=1),
        PlayerSeasonStats(player_id=players[5].id, club_id=club.id, league_id=league.id, season=2025, source_id=tm.id,
                          appearances=5, minutes=300, goals=0, assists=0, cards_yellow=0, cards_red=0),
    ])
    session.flush()
    score_run(session, 2024)
    app.dependency_overrides[get_db] = lambda: session
    c = TestClient(app)
    c.post("/api/v1/auth/register", json={"email": "scout@example.com", "password": PW})
    token = c.post("/api/v1/auth/login", data={"username": "scout@example.com", "password": PW}).json()["access_token"]
    c.headers["Authorization"] = f"Bearer {token}"
    yield c, players, league
    app.dependency_overrides.clear()
    session.close()
    transaction.rollback()
    connection.close()


def test_leagues_count_scored_players(seeded):
    c, _, league = seeded
    rows = c.get("/api/v1/leagues").json()
    assert next(r for r in rows if r["id"] == league.id)["scored_players"] == 12


def test_default_search_is_sorted_by_score(seeded):
    c, _, _ = seeded
    body = c.get("/api/v1/players").json()
    scores = [r["score"] for r in body["items"]]
    assert body["total"] == 12 and scores == sorted(scores, reverse=True)
    top = body["items"][0]
    assert top["name"] == "Test Defender 11" and top["price_eur"] == 12_000_000 and top["role"] == "CB"


def test_name_search_ignores_accents_and_case(seeded):
    c, players, _ = seeded
    items = c.get("/api/v1/players", params={"q": "MODRIC"}).json()["items"]
    assert [r["player_id"] for r in items] == [players[3].id]


def test_filters_sorting_and_paging(seeded):
    c, players, _ = seeded
    cheap = c.get("/api/v1/players", params={"max_price_eur": 3_000_000, "sort": "price_eur", "order": "asc"}).json()
    assert [r["price_eur"] for r in cheap["items"]] == [1_000_000, 2_000_000, 3_000_000]
    recent = c.get("/api/v1/players", params={"min_minutes_next": 900}).json()
    assert recent["total"] == 1 and recent["items"][0]["player_id"] == players[0].id
    assert recent["items"][0]["minutes_next"] == 1800  # summed across both clubs
    page2 = c.get("/api/v1/players", params={"limit": 5, "offset": 10}).json()
    assert page2["total"] == 12 and len(page2["items"]) == 2


def test_bad_query_is_422(seeded):
    c, _, _ = seeded
    assert c.get("/api/v1/players", params={"role": "XX"}).status_code == 422
    assert c.get("/api/v1/players", params={"age_min": 30, "age_max": 20}).status_code == 422
    assert c.get("/api/v1/players", params={"limit": 500}).status_code == 422


def test_profile_has_breakdown_value_and_recent_form(seeded):
    c, players, _ = seeded
    p = c.get(f"/api/v1/players/{players[0].id}").json()
    assert p["name"] == "Test Defender 0" and p["market_value"]["value_eur"] == 1_000_000
    assert p["market_value"]["source"] == "Transfermarkt"
    s = p["scores"][0]
    assert s["season"] == 2024 and s["role"] == "CB" and s["reliability"] in {"high", "medium"}
    labels = {m["label"] for m in s["metrics"]}
    assert "Interceptions per 90" in labels and "Dribbled past per 90" in s["dropped_metrics"]
    weights = [m["weight"] for m in s["metrics"]]
    assert weights == sorted(weights, reverse=True)
    assert p["season_stats"][0]["source"] == "API-Football" and p["season_stats"][0]["minutes"] == 2000
    rf = p["recent_form"]
    assert rf["season"] == 2025 and len(rf["rows"]) == 2
    assert rf["totals"] == {"appearances": 22, "minutes": 1800, "goals": 1, "assists": 2, "cards_yellow": 3, "cards_red": 1}


def test_profile_without_recent_form(seeded):
    c, players, _ = seeded
    rf = c.get(f"/api/v1/players/{players[1].id}").json()["recent_form"]
    assert rf["rows"] == [] and rf["totals"] is None


def test_unknown_player_is_404(seeded):
    c, _, _ = seeded
    r = c.get("/api/v1/players/99999999")
    assert r.status_code == 404 and r.json()["error"]["code"] == "NOT_FOUND"


def test_compare(seeded):
    c, players, _ = seeded
    r = c.get("/api/v1/players/compare", params=[("ids", players[0].id), ("ids", players[11].id)])
    assert r.status_code == 200 and r.json()["same_role"] is True and len(r.json()["players"]) == 2
    assert c.get("/api/v1/players/compare", params={"ids": players[0].id}).status_code == 422
    dup = [("ids", players[0].id), ("ids", players[0].id)]
    assert c.get("/api/v1/players/compare", params=dup).status_code == 422
    assert c.get("/api/v1/players/compare", params=[("ids", players[0].id), ("ids", 99999999)]).status_code == 404


def test_player_endpoints_need_login(seeded):
    c, players, _ = seeded
    anon = TestClient(app)
    for url in ["/api/v1/leagues", "/api/v1/players", f"/api/v1/players/{players[0].id}"]:
        assert anon.get(url).status_code == 401


def test_failed_login_uses_the_oauth2_error_format(seeded):
    c, _, _ = seeded
    r = c.post("/api/v1/auth/login", data={"username": "scout@example.com", "password": "Wrong-pass-2026"})
    assert r.status_code == 401
    assert r.json() == {"error": "invalid_grant", "error_description": "Wrong email or password"}
