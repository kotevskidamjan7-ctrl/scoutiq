"""Club improvement API (FR-11): club search, current squad, and POST /optimize/improve on scored data."""

import random
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import engine, get_db
from app.main import app
from app.models import Club, DataSource, League, MarketValuation, Player, PlayerSeasonStats
from app.scoring.run import run as score_run

PW = "Scout-pass-2026"
POS = {"GK": ("Goalkeeper", "GK", "Goalkeeper"), "CB": ("Centre-Back", "DEF", "Defender"),
       "FB": ("Left-Back", "DEF", "Defender"), "CM": ("Central Midfield", "MID", "Midfielder"),
       "AW": ("Right Winger", "FWD", "Attacker"), "ST": ("Centre-Forward", "FWD", "Attacker")}


def _add_player(db, rng, name, role, club, league, af, tm, q, value, minutes_next):
    sub, grp, apipos = POS[role]
    p = Player(full_name=name, name_normalized=name.lower(), birth_date=date(1996, 1, 1), position_group=grp,
               primary_position=sub, foot="right")
    db.add(p)
    db.flush()
    m = 2400
    f = m / 90
    def r(base):
        return max(0, int(base * f * (0.5 + q)))
    st = dict(appearances=28, lineups=26, minutes=m, rating=round(6.2 + q, 2), goals=r(0.4 if role == "ST" else 0.1),
              assists=r(0.1), shots_total=r(1.5), shots_on=r(0.6), passes_total=r(40), passes_key=r(0.8), tackles=r(1.5),
              interceptions=r(1.0), blocks=r(0.4), duels_total=r(9) + 30, duels_won=r(5) + 10, dribbles_attempts=r(1.5) + 5,
              dribbles_success=r(0.8) + 2, fouls_drawn=r(1), fouls_committed=10, cards_yellow=3, cards_red=0,
              penalty_scored=0, penalty_missed=0, saves=r(3) if role == "GK" else 0,
              goals_conceded=max(1, int(f * (1.6 - q))) if role == "GK" else 0, dribbled_past=r(0.5),
              position_reported=apipos)
    db.add(PlayerSeasonStats(player_id=p.id, club_id=club.id, league_id=league.id, season=2024, source_id=af.id, **st))
    db.add(PlayerSeasonStats(player_id=p.id, club_id=club.id, league_id=league.id, season=2024, source_id=tm.id,
                             minutes=m, appearances=28))
    if minutes_next:
        db.add(PlayerSeasonStats(player_id=p.id, club_id=club.id, league_id=league.id, season=2025, source_id=tm.id,
                                 minutes=minutes_next, appearances=minutes_next // 85))
    if value:
        db.add(MarketValuation(player_id=p.id, value_eur=value, valuation_date=date(2026, 6, 12),
                               valuation_type="transfermarkt", source_id=tm.id))
    return p


@pytest.fixture
def seeded():
    connection = engine.connect()
    transaction = connection.begin()
    db = Session(bind=connection, join_transaction_mode="create_savepoint")
    rng = random.Random(3)
    af = db.scalar(select(DataSource).where(DataSource.code == "api_football"))
    tm = db.scalar(select(DataSource).where(DataSource.code == "transfermarkt"))
    league = db.scalar(select(League).where(League.tm_competition_id == "GB1"))
    own = Club(name="Own Town FC", league_id=league.id)
    market_clubs = [Club(name=f"Market Club {i}", league_id=league.id) for i in range(4)]
    db.add_all([own, *market_clubs])
    db.flush()
    squad, market = [], []
    # own club: 3 per role, weak (q 0.1-0.4), no market value needed
    for role in POS:
        for i in range(3):
            squad.append(_add_player(db, rng, f"Own {role} {i}", role, own, league, af, tm, 0.1 + 0.1 * i, None, 2000))
    # market: 8 per role, stronger players cost more
    for role in POS:
        for i in range(8):
            q = 0.2 + 0.1 * i
            market.append(_add_player(db, rng, f"Market {role} {i}", role, market_clubs[i % 4], league, af, tm, q,
                                      int(200_000 + q ** 3 * 20_000_000) // 10_000 * 10_000, 2000))
    # a youngster with no league minutes: in the squad but not scored
    kid = Player(full_name="Own Academy Kid", name_normalized="own academy kid", birth_date=date(2008, 1, 1))
    db.add(kid)
    db.flush()
    db.add(PlayerSeasonStats(player_id=kid.id, club_id=own.id, league_id=league.id, season=2025, source_id=tm.id,
                             minutes=120, appearances=3))
    db.flush()
    score_run(db, 2024)
    app.dependency_overrides[get_db] = lambda: db
    c = TestClient(app)
    c.post("/api/v1/auth/register", json={"email": "club@example.com", "password": PW})
    token = c.post("/api/v1/auth/login", data={"username": "club@example.com", "password": PW}).json()["access_token"]
    c.headers["Authorization"] = f"Bearer {token}"
    yield c, own, squad, kid
    app.dependency_overrides.clear()
    db.close()
    transaction.rollback()
    connection.close()


def test_club_search_and_squad(seeded):
    c, own, squad, kid = seeded
    found = c.get("/api/v1/clubs", params={"q": "own town"}).json()
    assert [x["id"] for x in found] == [own.id]
    s = c.get(f"/api/v1/clubs/{own.id}/squad").json()
    assert s["club"]["name"] == "Own Town FC"
    ids = {p["player_id"] for p in s["players"]}
    assert ids == {p.id for p in squad} | {kid.id}
    kid_row = next(p for p in s["players"] if p["player_id"] == kid.id)
    assert kid_row["score"] is None and kid_row["role"] is None
    assert s["players"][-1]["player_id"] == kid.id  # unscored players listed last
    assert c.get("/api/v1/clubs/99999999/squad").status_code == 404


def test_improve_buys_better_players_and_reports_the_gain(seeded):
    c, own, squad, kid = seeded
    body = {"formation": "4-3-3", "budget_eur": 15_000_000, "max_signings": 2,
            "owned_player_ids": [p.id for p in squad] + [kid.id]}
    r = c.post("/api/v1/optimize/improve", json=body)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["status"] == "optimal"
    signings = [p for p in d["team"]["players"] if p["signing"]]
    assert 1 <= len(signings) <= 2
    assert d["team"]["cost_eur"] == sum(p["price_eur"] for p in signings) <= 15_000_000
    assert d["current"] is not None and all(not p["signing"] for p in d["current"]["players"])
    assert d["gain"] == pytest.approx(d["team"]["total_score"] - d["current"]["total_score"], abs=0.05)
    assert d["gain"] > 0
    assert [u["name"] for u in d["unscored"]] == ["Own Academy Kid"]
    for alt in d["alternatives"]:
        assert {p["player_id"] for p in alt["players"] if p["signing"]} != {p["player_id"] for p in signings}


def test_zero_budget_returns_the_current_xi(seeded):
    c, own, squad, kid = seeded
    d = c.post("/api/v1/optimize/improve", json={"formation": "4-3-3", "budget_eur": 0, "max_signings": 3,
                                                 "owned_player_ids": [p.id for p in squad]}).json()
    assert d["gain"] == 0 and d["team"]["cost_eur"] == 0
    assert not any(p["signing"] for p in d["team"]["players"])


def test_locked_players_start(seeded):
    c, own, squad, kid = seeded
    weakest_st = next(p for p in squad if p.full_name == "Own ST 0")
    d = c.post("/api/v1/optimize/improve", json={"formation": "4-3-3", "budget_eur": 50_000_000, "max_signings": 3,
                                                 "owned_player_ids": [p.id for p in squad],
                                                 "locked_player_ids": [weakest_st.id]}).json()
    assert weakest_st.id in {p["player_id"] for p in d["team"]["players"]}


def test_squad_that_cannot_fill_the_formation(seeded):
    c, own, squad, kid = seeded
    no_gk = [p.id for p in squad if " GK " not in p.full_name]
    d = c.post("/api/v1/optimize/improve", json={"formation": "4-3-3", "budget_eur": 0, "max_signings": 0,
                                                 "owned_player_ids": no_gk}).json()
    assert d["current_missing"] == {"GK": 1} and d["current"] is None and d["team"] is None
    # one change alone cannot help (no signing allowed AND no money), so the suggestion carries both
    changes = [s["change"] for s in d["diagnosis"]["suggestions"]]
    assert any(ch.startswith("allow 1 signing and raise the budget to €") for ch in changes), changes


def test_bad_improve_requests(seeded):
    c, own, squad, kid = seeded
    ids = [p.id for p in squad]
    assert c.post("/api/v1/optimize/improve", json={"formation": "5-5-0", "budget_eur": 1, "owned_player_ids": ids}).status_code == 422
    assert c.post("/api/v1/optimize/improve", json={"formation": "4-3-3", "budget_eur": 1, "owned_player_ids": ids,
                                                    "locked_player_ids": [123456789]}).status_code == 422
    assert c.post("/api/v1/optimize/improve", json={"formation": "4-3-3", "budget_eur": 1, "owned_player_ids": []}).status_code == 422
    assert TestClient(app).post("/api/v1/optimize/improve", json={}).status_code == 401



def test_players_who_left_are_not_bought_back(seeded):
    """Requested 2026-11-06: a player unticked as 'left the club' is never suggested as a signing."""
    c, own, squad, kid = seeded
    owned = [p.id for p in squad]
    body = {"formation": "4-3-3", "budget_eur": 500_000_000, "max_signings": 1, "owned_player_ids": owned,
            "signing_roles": ["ST"]}
    allowed = c.post("/api/v1/optimize/improve", json=body).json()
    first_choice = next(p["player_id"] for p in allowed["team"]["players"] if p["signing"])
    # say that striker used to be ours and has left: he must not be suggested any more
    excluded = c.post("/api/v1/optimize/improve", json={**body, "left_player_ids": [first_choice]}).json()
    bought = {p["player_id"] for t in [excluded["team"], *excluded["alternatives"]] for p in t["players"] if p["signing"]}
    assert first_choice not in bought
    assert excluded["team"]["total_score"] <= allowed["team"]["total_score"]
    bad = c.post("/api/v1/optimize/improve", json={**body, "left_player_ids": [owned[0]]})
    assert bad.status_code == 422
