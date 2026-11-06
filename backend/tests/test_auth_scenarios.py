"""Accounts, roles and saved scenarios (FR-15, US-08, NFR-07)."""

from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import engine, get_db
from app.main import app
from app.models import AppUser
from app.scoring.run import run as score_run
from tests.test_scoring import _seed_centre_backs

PW = "Scout-pass-2026"


@pytest.fixture
def db():
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    app.dependency_overrides[get_db] = lambda: session
    yield session
    app.dependency_overrides.clear()
    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture
def client(db):
    return TestClient(app)


def login(client, email, password=PW) -> dict:
    client.post("/api/v1/auth/register", json={"email": email, "password": password})
    token = client.post("/api/v1/auth/login", data={"username": email, "password": password}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


# ---------- accounts ----------

def test_register_login_me(client, db):
    r = client.post("/api/v1/auth/register", json={"email": "  Ana@Example.com ", "password": PW})
    assert r.status_code == 201 and r.json()["email"] == "ana@example.com" and r.json()["role"] == "scout"
    stored = db.scalar(select(AppUser).where(AppUser.email == "ana@example.com"))
    assert stored.password_hash != PW and stored.password_hash.startswith("$argon2")  # never plain text

    tok = client.post("/api/v1/auth/login", data={"username": "ana@example.com", "password": PW}).json()
    assert tok["token_type"] == "bearer" and tok["expires_in_minutes"] == get_settings().jwt_minutes
    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {tok['access_token']}"})
    assert me.status_code == 200 and me.json()["email"] == "ana@example.com"


def test_duplicate_email_is_409(client):
    client.post("/api/v1/auth/register", json={"email": "a@example.com", "password": PW})
    r = client.post("/api/v1/auth/register", json={"email": "A@example.com", "password": PW})
    assert r.status_code == 409 and r.json()["error"]["code"] == "CONFLICT"


@pytest.mark.parametrize("email, password", [
    ("not-an-email", PW), ("a@example.com", "short1"), ("a@example.com", "1234567890123"),
    ("a@example.com", "aaaaaaaaaaaa"),
])
def test_bad_registration_is_422(client, email, password):
    assert client.post("/api/v1/auth/register", json={"email": email, "password": password}).status_code == 422


def test_wrong_password_and_unknown_user_look_the_same(client):
    client.post("/api/v1/auth/register", json={"email": "b@example.com", "password": PW})
    wrong = client.post("/api/v1/auth/login", data={"username": "b@example.com", "password": "Wrong-pass-2026"})
    unknown = client.post("/api/v1/auth/login", data={"username": "nobody@example.com", "password": PW})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()  # no hint whether the account exists


def test_missing_tampered_and_expired_tokens_are_rejected(client):
    headers = login(client, "c@example.com")
    assert client.get("/api/v1/auth/me").status_code == 401
    assert client.get("/api/v1/auth/me", headers={"Authorization": headers["Authorization"] + "x"}).status_code == 401
    me = client.get("/api/v1/auth/me", headers=headers).json()
    expired = jwt.encode({"sub": str(me["id"]), "role": "scout",
                          "exp": datetime.now(timezone.utc) - timedelta(minutes=1)},
                         get_settings().jwt_secret, algorithm="HS256")
    assert client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {expired}"}).status_code == 401
    forged = jwt.encode({"sub": str(me["id"]), "role": "admin", "exp": datetime.now(timezone.utc) + timedelta(hours=1)},
                        "a-different-secret-that-is-long-enough-for-hs256", algorithm="HS256")
    assert client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {forged}"}).status_code == 401


# ---------- roles ----------

def test_admin_endpoint_needs_admin_role(client, db):
    scout = login(client, "scout@example.com")
    assert client.get("/api/v1/admin/users", headers=scout).status_code == 403
    db.scalar(select(AppUser).where(AppUser.email == "scout@example.com")).role = "admin"
    db.flush()
    r = client.get("/api/v1/admin/users", headers=scout)
    assert r.status_code == 200 and any(u["email"] == "scout@example.com" for u in r.json())


# ---------- saved scenarios ----------

def test_save_list_reopen_delete_and_privacy(client, db):
    _seed_centre_backs(db, n=12)
    score_run(db, 2024)
    ana, ben = login(client, "ana@example.com"), login(client, "ben@example.com")
    request = {"budget_eur": 10_000_000, "needs": {"CB": 2}, "min_minutes_next": 0}

    saved = client.post("/api/v1/scenarios", json={"name": "Two centre-backs", "request": request}, headers=ana)
    assert saved.status_code == 201
    s = saved.json()
    assert s["status"] == "optimal" and s["result"]["team"]["cost_eur"] <= 10_000_000

    listed = client.get("/api/v1/scenarios", headers=ana).json()
    assert [x["id"] for x in listed] == [s["id"]] and listed[0]["total_score"] == s["result"]["team"]["total_score"]

    reopened = client.get(f"/api/v1/scenarios/{s['id']}", headers=ana).json()
    assert reopened["request"]["budget_eur"] == 10_000_000 and reopened["result"] == s["result"]  # same inputs+result

    assert client.get("/api/v1/scenarios", headers=ben).json() == []                      # Ben sees nothing
    assert client.get(f"/api/v1/scenarios/{s['id']}", headers=ben).status_code == 404     # and cannot open it
    assert client.delete(f"/api/v1/scenarios/{s['id']}", headers=ben).status_code == 404  # or delete it

    assert client.delete(f"/api/v1/scenarios/{s['id']}", headers=ana).status_code == 204
    assert client.get(f"/api/v1/scenarios/{s['id']}", headers=ana).status_code == 404


def test_scenarios_need_login(client):
    assert client.get("/api/v1/scenarios").status_code == 401


def test_set_password_command_uses_registration_rules():
    from app.users_cli import check_password
    assert check_password("a@example.com", "Scout-pass-2026") is None
    assert check_password("a@example.com", "short") is not None
    assert check_password("a@example.com", "1234567890123") is not None  # digits only
