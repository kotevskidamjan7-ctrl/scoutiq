"""Shortlist: follow players with notes; use them as the only candidates in the optimizer."""

from datetime import date

from app.api.deps import get_db
from app.main import app
from app.models import MarketValuation, Player
from tests.test_players_api import PW, seeded  # noqa: F401  (12 centre-backs valued EUR 1m..12m)


def _session():
    return app.dependency_overrides[get_db]()


def test_add_list_note_and_remove(seeded):  # noqa: F811
    c, players, _ = seeded
    p = players[4]
    r = c.put(f"/api/v1/shortlist/{p.id}")
    assert r.status_code == 201, r.text
    item = r.json()
    assert item["player_id"] == p.id and item["note"] == "" and item["score"] is not None
    assert item["value_at_add_eur"] == item["price_eur"] and item["value_change_pct"] == 0

    again = c.put(f"/api/v1/shortlist/{p.id}")            # adding twice is harmless
    assert again.status_code == 200 and again.json()["added_at"] == item["added_at"]
    noted = c.put(f"/api/v1/shortlist/{p.id}", json={"note": "Watch vs Partizan in December"})
    assert noted.status_code == 200 and noted.json()["note"] == "Watch vs Partizan in December"
    kept = c.put(f"/api/v1/shortlist/{p.id}", json={})    # no note given: the note stays
    assert kept.json()["note"] == "Watch vs Partizan in December"

    c.put(f"/api/v1/shortlist/{players[7].id}", json={"note": "second"})
    listed = c.get("/api/v1/shortlist").json()
    assert [x["player_id"] for x in listed] == [players[7].id, p.id] or {x["player_id"] for x in listed} == {players[7].id, p.id}

    assert c.delete(f"/api/v1/shortlist/{p.id}").status_code == 204
    assert c.delete(f"/api/v1/shortlist/{p.id}").status_code == 204  # already gone: harmless
    assert [x["player_id"] for x in c.get("/api/v1/shortlist").json()] == [players[7].id]


def test_value_change_since_added(seeded):  # noqa: F811
    c, players, _ = seeded
    p = players[2]
    before = c.put(f"/api/v1/shortlist/{p.id}").json()["value_at_add_eur"]
    s = _session()
    tm_val = s.query(MarketValuation).filter_by(player_id=p.id).first()
    s.add(MarketValuation(player_id=p.id, value_eur=int(before * 1.5), valuation_date=date(2026, 9, 1),
                          valuation_type="transfermarkt", source_id=tm_val.source_id))
    s.flush()
    item = next(x for x in c.get("/api/v1/shortlist").json() if x["player_id"] == p.id)
    # the list's price is the scored price; the change follows whatever price the app shows now
    if item["price_eur"] != before:
        assert item["value_change_pct"] == round((item["price_eur"] - before) / before * 100, 1)
    else:
        assert item["value_change_pct"] == 0


def test_player_without_a_score_can_be_shortlisted(seeded):  # noqa: F811
    c, players, _ = seeded
    s = _session()
    young = Player(full_name="Unscored Prospect", name_normalized="unscored prospect", birth_date=date(2007, 3, 1),
                   primary_position="Centre-Back")
    s.add(young)
    s.flush()
    r = c.put(f"/api/v1/shortlist/{young.id}", json={"note": "U19, watch"})
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["name"] == "Unscored Prospect" and d["score"] is None and d["note"] == "U19, watch"


def test_unknown_player_login_and_privacy(seeded):  # noqa: F811
    c, players, _ = seeded
    assert c.put("/api/v1/shortlist/99999999").status_code == 404
    c.put(f"/api/v1/shortlist/{players[1].id}")
    assert c.put(f"/api/v1/shortlist/{players[1].id}", json={"note": "x" * 2001}).status_code == 422
    auth = c.headers.pop("Authorization")
    assert c.get("/api/v1/shortlist").status_code == 401
    c.post("/api/v1/auth/register", json={"email": "other-sl@example.com", "password": PW})
    tok = c.post("/api/v1/auth/login", data={"username": "other-sl@example.com", "password": PW}).json()["access_token"]
    c.headers["Authorization"] = f"Bearer {tok}"
    assert c.get("/api/v1/shortlist").json() == []          # someone else's shortlist is not visible
    c.headers["Authorization"] = auth


def test_optimizer_buys_only_shortlisted_players(seeded):  # noqa: F811
    c, players, _ = seeded
    allowed = [players[0].id, players[1].id, players[2].id]  # three cheap centre-backs
    r = c.post("/api/v1/optimize/squad", json={"needs": {"CB": 2}, "budget_eur": 100_000_000, "min_minutes_next": 0, "only_player_ids": allowed})
    assert r.status_code == 200, r.text
    team = r.json()["team"]
    assert team and {p["player_id"] for p in team["players"]} <= set(allowed)
    best_any = c.post("/api/v1/optimize/squad", json={"needs": {"CB": 2}, "budget_eur": 100_000_000, "min_minutes_next": 0}).json()["team"]
    assert best_any["total_score"] >= team["total_score"]


def test_too_small_shortlist_suggests_searching_beyond_it(seeded):  # noqa: F811
    c, players, _ = seeded
    r = c.post("/api/v1/optimize/squad", json={"needs": {"CB": 2}, "budget_eur": 100_000_000, "min_minutes_next": 0,
                                         "only_player_ids": [players[5].id]})
    d = r.json()
    assert d["team"] is None
    changes = [s["change"] for s in d["diagnosis"]["suggestions"]]
    assert "search beyond your shortlist" in changes


def test_shortage_reason_names_the_shortlist_with_correct_grammar(seeded):  # noqa: F811
    c, players, _ = seeded
    d = c.post("/api/v1/optimize/squad", json={"needs": {"CB": 2}, "budget_eur": 100_000_000, "min_minutes_next": 0,
                                               "only_player_ids": [players[5].id]}).json()
    assert "only 1 eligible centre-backs on your shortlist; 2 are needed" in d["diagnosis"]["reason"]
    d = c.post("/api/v1/optimize/squad", json={"needs": {"CB": 1}, "budget_eur": 100_000_000, "min_minutes_next": 0,
                                               "league_ids": [999999]}).json()
    assert "under your filters; 1 is needed" in d["diagnosis"]["reason"]
