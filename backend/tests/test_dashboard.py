"""Dashboard (FR-04): coverage per league, provisional flag, and value-for-money picks."""

from datetime import date

import pytest

from app.players.dashboard import budget_picks, league_status, value_picks
from app.players.service import Row
from tests.test_players_api import seeded  # noqa: F401  (fixture: 12 scored centre-backs, logged-in client)


def row(pid, role="ST", vfm=5.0, score=70.0, reliability="high", minutes_next=1500, price=1_000_000, league_id=1):
    return Row(player_id=pid, name=f"P{pid}", name_normalized=f"p{pid}", birth_date=date(1998, 1, 1), age=28,
               nationality=None, role=role, league_id=league_id, league="L", club="C", score=score, score_adjusted=None,
               value_for_money=vfm, reliability=reliability, minutes=2000, minutes_next=minutes_next, price_eur=price,
               valuation_date="2026-06-12", position_consistent=True)


def test_league_status():
    assert league_status(0, 0.0) == "no_data"
    assert league_status(200, 0.415) == "provisional"
    assert league_status(500, 0.969) == "complete"
    assert league_status(500, 0.90) == "complete"


def test_value_picks_rules():
    rows = [
        row(1, vfm=30), row(2, vfm=20), row(3, vfm=10), row(4, vfm=40),
        row(5, vfm=50, reliability="low"),     # unreliable score: excluded
        row(6, vfm=60, minutes_next=300),      # not playing in 2025/26: excluded
        row(7, vfm=None),                      # value for money hidden for the role: excluded
        row(8, vfm=70, price=None),            # no valuation: excluded
        row(10, vfm=80, score=12.0),           # cheap but weak: excluded by the score floor
        row(11, vfm=-3.0),                     # overpriced: never a value pick
        row(9, role="CB", vfm=5),
    ]
    picks = value_picks(rows)
    assert [r.player_id for r in picks["ST"]] == [4, 1, 2]
    assert [r.player_id for r in picks["CB"]] == [9]
    assert picks["GK"] == []


def test_dashboard_endpoint(seeded):  # noqa: F811
    c, players, league = seeded
    r = c.get("/api/v1/stats/dashboard")
    assert r.status_code == 200
    d = r.json()
    assert d["season"] == 2024 and d["recent_season"] == 2025
    assert d["totals"]["players_scored"] == 12
    assert d["totals"]["still_playing"] == 1  # only player 0 has 900+ minutes in 2025/26 (1,800)
    gb = next(lg for lg in d["leagues"] if lg["id"] == league.id)
    assert gb["scored"] == 12 and gb["regulars"] == 12 and gb["roles"] == {"CB": 12}
    assert gb["median_value_eur"] == 6_500_000
    # every Transfermarkt regular in the seed has an API-Football line
    assert gb["status"] == "complete" and gb["coverage"] == 1.0
    # value for money is hidden for these centre-backs (and only one still plays), so there are no picks
    assert d["value_picks"]["CB"] == []
    assert set(d["value_picks"]) == {"GK", "CB", "FB", "CM", "AW", "ST"}
    assert d["model"]["version"] == "v1.0"


def test_dashboard_needs_login(seeded):  # noqa: F811
    from fastapi.testclient import TestClient
    from app.main import app
    assert TestClient(app).get("/api/v1/stats/dashboard").status_code == 401


def test_budget_picks_rank_by_score_under_the_cap():
    rows = [
        row(1, role="CB", vfm=None, score=80, price=900_000),
        row(2, role="CB", vfm=None, score=90, price=2_500_000),
        row(3, role="CB", vfm=None, score=99, price=40_000_000),     # over every cap
        row(4, role="CB", vfm=None, score=95, price=3_000_000),      # exactly at the cap: included
        row(5, role="CB", vfm=None, score=97, price=500_000, reliability="low"),   # unreliable
        row(6, role="CB", vfm=None, score=96, price=500_000, minutes_next=0),      # not playing now
        row(7, role="CB", vfm=None, score=85, price=None),           # no valuation
    ]
    assert [r.player_id for r in budget_picks(rows, 1_000_000)["CB"]] == [1]
    assert [r.player_id for r in budget_picks(rows, 3_000_000)["CB"]] == [4, 2, 1]
    assert budget_picks(rows, 3_000_000)["GK"] == []


def test_dashboard_reports_budget_lists_and_hidden_roles(seeded):  # noqa: F811
    c, players, league = seeded
    d = c.get("/api/v1/stats/dashboard").json()
    assert set(d["budget_picks"]) == {"1000000", "3000000", "10000000"}
    assert d["value_for_money_shown"]["CB"] is False
    # centre-backs still playing 900+ in 2025/26: only player 0 (EUR 1m)
    assert [r["player_id"] for r in d["budget_picks"]["1000000"]["CB"]] == [players[0].id]


def test_dashboard_age_limit(seeded):  # noqa: F811
    c, players, league = seeded
    d = c.get("/api/v1/stats/dashboard", params={"max_age": 20}).json()
    assert d["max_age"] == 20
    assert all(r["age"] <= 20 for lists in d["budget_picks"].values() for rs in lists.values() for r in rs)
    assert c.get("/api/v1/stats/dashboard", params={"max_age": 99}).status_code == 422
