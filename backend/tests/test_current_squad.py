"""Current squad from API-Football (players/squads), matched to the data. No real requests: the fetch is faked."""

from datetime import date

import pytest
from sqlalchemy import select

import app.players.current_squad as CS
from app.api.deps import get_db
from app.main import app
from app.models import ClubSourceId, DataSource, Player, PlayerSourceId
from tests.test_api_improve import seeded  # noqa: F401

TODAY = date(2026, 11, 15)


def _session():
    return app.dependency_overrides[get_db]()


def _link(s, own, squad):
    af = s.scalar(select(DataSource).where(DataSource.code == "api_football"))
    s.add(ClubSourceId(source_id=af.id, external_id="999", club_id=own.id))
    for i, p in enumerate(squad[:2]):
        s.add(PlayerSourceId(source_id=af.id, external_id=str(1001 + i), player_id=p.id, match_method="exact"))
    newcomer = Player(full_name="Illan Meslier", name_normalized="illan meslier", birth_date=date(2000, 3, 2))
    s.add(newcomer)
    s.flush()
    return newcomer


def test_current_squad_matches_by_id_and_name_and_lists_the_rest(seeded, monkeypatch):  # noqa: F811
    c, own, squad, kid = seeded
    newcomer = _link(_session(), own, squad)
    api = [{"id": 1001, "name": squad[0].full_name, "age": 30, "position": "Goalkeeper"},
           {"id": 1002, "name": squad[1].full_name, "age": 30, "position": "Goalkeeper"},
           {"id": 7777, "name": "I. Meslier", "age": 26, "position": "Goalkeeper"},
           {"id": 8888, "name": "Z. Nobodyknows", "age": 19, "position": "Attacker"}]
    calls = []
    monkeypatch.setattr(CS, "fetch", lambda team, today: calls.append(team) or api)
    r = c.post(f"/api/v1/clubs/{own.id}/squad/current")
    assert r.status_code == 200, r.text
    d = r.json()
    assert calls == ["999"]
    assert {p["player_id"] for p in d["players"]} == {squad[0].id, squad[1].id, newcomer.id}
    assert d["joined_ids"] == [newcomer.id]
    assert set(d["left_ids"]) == {p.id for p in squad[2:]} | {kid.id}
    assert d["not_in_data"] == [{"name": "Z. Nobodyknows", "age": 19, "position": "Attacker"}]
    assert d["matched_by_name"] == 1
    assert d["club"]["name"] == "Own Town FC"


def test_name_match_needs_one_clear_candidate_and_the_right_age(seeded):  # noqa: F811
    c, own, squad, kid = seeded
    s = _session()
    s.add_all([Player(full_name="Ivan Petrov", name_normalized="ivan petrov", birth_date=date(1999, 1, 1)),
               Player(full_name="Igor Petrov", name_normalized="igor petrov", birth_date=date(1999, 6, 1)),
               Player(full_name="Ante Kovac", name_normalized="ante kovac", birth_date=date(1995, 1, 1))])
    s.flush()
    assert CS._by_name(s, "I. Petrov", 27, TODAY) is None          # two players fit: no guess
    assert CS._by_name(s, "A. Kovač", 31, TODAY) is not None       # accents and initial
    assert CS._by_name(s, "A. Kovač", 22, TODAY) is None           # wrong age
    assert CS._by_name(s, "Ante Kovac", None, TODAY) is not None   # full name, no age given


def test_club_without_api_link_and_api_problems_give_clear_messages(seeded, monkeypatch):  # noqa: F811
    c, own, squad, kid = seeded
    r = c.post(f"/api/v1/clubs/{own.id}/squad/current")
    assert r.status_code == 404 and "not linked to an API-Football team" in r.json()["error"]["message"]
    _link(_session(), own, squad)

    def quota(team, today):
        raise CS.SquadUnavailable("Today's API-Football requests are used up. Try again after 01:00.", 429)
    monkeypatch.setattr(CS, "fetch", quota)
    r = c.post(f"/api/v1/clubs/{own.id}/squad/current")
    assert r.status_code == 429 and "after 01:00" in r.json()["error"]["message"]
    monkeypatch.setattr(CS, "fetch", lambda team, today: [])
    assert c.post(f"/api/v1/clubs/{own.id}/squad/current").status_code == 502
    assert c.post("/api/v1/clubs/99999999/squad/current").status_code == 404


def test_cache_is_per_week():
    assert CS._cache_dir(date(2026, 11, 15)).name == "2026-W46"
    assert CS._cache_dir(date(2026, 11, 16)).name == "2026-W47"


def test_login_required(seeded):  # noqa: F811
    c, own, squad, kid = seeded
    auth = c.headers.pop("Authorization")
    assert c.post(f"/api/v1/clubs/{own.id}/squad/current").status_code == 401
    c.headers["Authorization"] = auth
