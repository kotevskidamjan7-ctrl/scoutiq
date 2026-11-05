"""API tests for POST /api/v1/optimize/squad (input validation, error format, responses)."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.session import engine, get_db
from app.main import app
from app.scoring.run import run as score_run
from tests.test_scoring import _seed_centre_backs

URL = "/api/v1/optimize/squad"


@pytest.fixture
def client():
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    _seed_centre_backs(session, n=12)  # synthetic centre-backs valued EUR 1m..12m
    score_run(session, 2024)
    app.dependency_overrides[get_db] = lambda: session
    c = TestClient(app)
    c.post("/api/v1/auth/register", json={"email": "scout@example.com", "password": "Scout-pass-2026"})
    token = c.post("/api/v1/auth/login", data={"username": "scout@example.com", "password": "Scout-pass-2026"}).json()
    c.headers["Authorization"] = f"Bearer {token['access_token']}"
    yield c
    app.dependency_overrides.clear()
    session.close()
    transaction.rollback()
    connection.close()


def test_optimal_team(client):
    r = client.post(URL, json={"budget_eur": 10_000_000, "needs": {"CB": 2}, "min_minutes_next": 0})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "optimal" and len(body["team"]["players"]) == 2
    assert body["team"]["cost_eur"] <= 10_000_000
    assert body["remaining_budget_eur"] == 10_000_000 - body["team"]["cost_eur"]
    assert any("not transfer fees" in n for n in body["notes"])


def test_infeasible_is_200_with_diagnosis(client):
    r = client.post(URL, json={"budget_eur": 1_000_000, "needs": {"CB": 2}, "min_minutes_next": 0})
    body = r.json()
    assert r.status_code == 200 and body["status"] == "infeasible" and body["team"] is None
    assert body["diagnosis"]["cheapest_cost_eur"] == 3_000_000


def test_recent_form_filter_is_on_by_default(client):
    # the synthetic players have no 2025/26 minutes, so the default filter leaves nobody
    body = client.post(URL, json={"budget_eur": 50_000_000, "needs": {"CB": 2}}).json()
    assert body["status"] == "infeasible" and body["eligible_players"] == 0


@pytest.mark.parametrize("payload", [
    {"budget_eur": -5, "needs": {"CB": 1}},                                    # negative budget
    {"budget_eur": 1_000_000},                                                 # neither formation nor needs
    {"budget_eur": 1_000_000, "formation": "4-3-3", "needs": {"CB": 1}},      # both
    {"budget_eur": 1_000_000, "formation": "2-2-6"},                          # unknown formation
    {"budget_eur": 1_000_000, "needs": {"XX": 1}},                            # unknown role
    {"budget_eur": 1_000_000, "needs": {"CB": 0}},                            # nobody requested
    {"budget_eur": 1_000_000, "needs": {"CB": 1}, "age_min": 30, "age_max": 20},
    {"budget_eur": 1_000_000, "needs": {"CB": 1}, "alternatives": 9},
])
def test_invalid_input_is_rejected_with_422(client, payload):
    assert client.post(URL, json=payload).status_code == 422


def test_optimizer_requires_login(client):
    del client.headers["Authorization"]
    r = client.post(URL, json={"budget_eur": 10_000_000, "needs": {"CB": 2}})
    assert r.status_code == 401 and r.json()["error"]["code"] == "UNAUTHORIZED"


def test_validation_errors_use_the_api_error_format(client):
    body = client.post(URL, json={"budget_eur": -5, "needs": {"CB": 1}}).json()
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert any(d["field"] == "budget_eur" for d in body["error"]["details"])
