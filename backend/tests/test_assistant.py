"""Assistant (FR-15): the rule-based parser on 40 labelled requests (English and Macedonian), the AI
fallback, and the endpoint. Every case is compared field by field with the expected filters."""

import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.assistant import llm, rules, service
from app.assistant.filters import AssistantFilters
from app.core.config import get_settings
from app.db.session import get_db
from app.main import app

CASES = json.loads((Path(__file__).parent / "fixtures" / "assistant_tuning.json").read_text(encoding="utf-8"))


def expected(case) -> dict:
    return AssistantFilters(**case["expect"]).model_dump()


@pytest.mark.parametrize("case", CASES, ids=[c["text"][:40] for c in CASES])
def test_rules_parse_each_labelled_request(case):
    got, _ = rules.parse(case["text"])
    assert got.model_dump() == expected(case)


def test_rules_never_produce_invalid_filters():
    for text in ["", "???", "under 99 years", "older than 50 under 20", "€5", "999999m striker", "4-9-9", "u99"]:
        f, _ = rules.parse(text)
        AssistantFilters.model_validate(f.model_dump())   # always a valid filter set


@pytest.mark.parametrize("text,age_min,age_max", [
    ("winger not older than 24", None, 24), ("striker no older than 30", None, 30),
    ("keeper not younger than 25", 25, None), ("штопер не постар од 26", None, 26),
])
def test_negated_ages_are_never_inverted(text, age_min, age_max):
    """Found by the holdout evaluation (2026-11-06): 'not older than 24' was read as 'older than 24'."""
    f, _ = rules.parse(text)
    assert (f.age_min, f.age_max) == (age_min, age_max)


def test_a_bare_amount_depends_on_the_page():
    """Found in the browser (2026-11-06): '25m' on Improve my club was read as a price, not the budget."""
    text = "a full-back and a striker, 25m, under 27"
    assert rules.parse(text, "price")[0].max_price_eur == 25_000_000
    on_improve = rules.parse(text, "budget")[0]
    assert on_improve.budget_eur == 25_000_000 and on_improve.max_price_eur is None
    # an explicit word always wins
    assert rules.parse("striker under 3m", "budget")[0].max_price_eur == 3_000_000
    assert rules.parse("budget 3m", "price")[0].budget_eur == 3_000_000


def test_contradictory_ages_keep_the_upper_limit():
    f, _ = rules.parse("striker over 30 and under 25")
    assert f.age_max == 24 and f.age_min is None


# ---------- AI parser: failures always fall back to rules ----------

class FakeResponse:
    def __init__(self, status, payload):
        self.status_code, self._payload = status, payload

    def json(self):
        return self._payload


def test_ai_answer_is_validated(monkeypatch):
    good = {"content": [{"type": "tool_use", "name": "set_filters", "input": {"roles": ["ST"], "age_max": 24}}]}
    monkeypatch.setattr(httpx, "post", lambda *a, **k: FakeResponse(200, good))
    assert llm.parse("x", "key", "model").model_dump() == AssistantFilters(roles=["ST"], age_max=24).model_dump()
    bad = {"content": [{"type": "tool_use", "name": "set_filters", "input": {"roles": ["XX"]}}]}
    monkeypatch.setattr(httpx, "post", lambda *a, **k: FakeResponse(200, bad))
    with pytest.raises(llm.LLMUnavailable, match="not valid"):
        llm.parse("x", "key", "model")


@pytest.mark.parametrize("status,payload,message", [
    (400, {"error": {"message": "Your credit balance is too low"}}, "no credit"),
    (401, {"error": {"message": "invalid x-api-key"}}, "not accepted"),
    (529, {"error": {"message": "overloaded"}}, "answered 529"),
])
def test_ai_errors_explain_themselves(monkeypatch, status, payload, message):
    monkeypatch.setattr(httpx, "post", lambda *a, **k: FakeResponse(status, payload))
    with pytest.raises(llm.LLMUnavailable, match=message):
        llm.parse("x", "key", "model")


def test_network_error_is_unavailable(monkeypatch):
    def boom(*a, **k):
        raise httpx.ConnectTimeout("slow")
    monkeypatch.setattr(httpx, "post", boom)
    with pytest.raises(llm.LLMUnavailable, match="could not reach"):
        llm.parse("x", "key", "model")


# ---------- endpoint ----------

@pytest.fixture
def client():
    from sqlalchemy.orm import Session
    from app.db.session import engine
    connection = engine.connect()
    transaction = connection.begin()
    db = Session(bind=connection, join_transaction_mode="create_savepoint")
    app.dependency_overrides[get_db] = lambda: db
    c = TestClient(app)
    c.post("/api/v1/auth/register", json={"email": "ask@example.com", "password": "Scout-pass-2026"})
    token = c.post("/api/v1/auth/login", data={"username": "ask@example.com", "password": "Scout-pass-2026"}).json()["access_token"]
    c.headers["Authorization"] = f"Bearer {token}"
    yield c
    app.dependency_overrides.clear()
    db.close()
    transaction.rollback()
    connection.close()


def test_endpoint_without_key_uses_rules(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "anthropic_api_key", None)
    r = client.post("/api/v1/assistant/interpret", json={"text": "a young striker from La Liga under 3m"}).json()
    assert r["engine"] == "rules" and r["note"] is None
    assert r["filters"]["roles"] == ["ST"] and r["filters"]["leagues"] == ["ES1"] and len(r["league_ids"]) == 1
    assert r["understood"] == ["Striker", "Age 23 or younger", "Up to €3m per player", "La Liga"]


def test_leagues_not_in_the_data_are_reported_not_applied(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "anthropic_api_key", None)
    r = client.post("/api/v1/assistant/interpret", json={"text": "winger from Belgium"}).json()
    assert r["filters"]["leagues"] == [] and r["league_ids"] == []
    assert r["not_applied"] == ["Belgian Pro League (not in the app's data yet)"]


def test_ai_failure_falls_back_with_a_note(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "anthropic_api_key", "sk-test")
    monkeypatch.setattr(httpx, "post", lambda *a, **k: FakeResponse(400, {"error": {"message": "credit balance is too low"}}))
    r = client.post("/api/v1/assistant/interpret", json={"text": "goalkeeper under 25"}).json()
    assert r["engine"] == "rules" and "no credit" in r["note"] and r["filters"]["age_max"] == 24


def test_ai_used_when_it_works(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "anthropic_api_key", "sk-test")
    answer = {"content": [{"type": "tool_use", "name": "set_filters", "input": {"roles": ["CM"], "leagues": ["IT1"]}}]}
    monkeypatch.setattr(httpx, "post", lambda *a, **k: FakeResponse(200, answer))
    r = client.post("/api/v1/assistant/interpret", json={"text": "regista from Serie A"}).json()
    assert r["engine"] == "ai" and r["understood"] == ["Central midfielder", "Serie A"]


def test_endpoint_needs_login_and_text():
    assert TestClient(app).post("/api/v1/assistant/interpret", json={"text": "striker"}).status_code == 401
