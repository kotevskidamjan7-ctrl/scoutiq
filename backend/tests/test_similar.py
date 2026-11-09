"""Similar players: nearest statistical profiles in the same role."""

import pytest

from app.players.similar import MIN_SHARED_WEIGHT, differences, distance
from tests.test_players_api import seeded  # noqa: F401  (fixture: 12 centre-backs, stats rising with the index)


# --- the measure ---------------------------------------------------------------------------------

def test_distance_is_weighted_rms_of_percentile_gaps():
    w = {"a": 3.0, "b": 1.0}
    assert distance({"a": 50, "b": 50}, {"a": 50, "b": 50}, w) == 0
    assert distance({"a": 50, "b": 50}, {"a": 60, "b": 50}, w) == pytest.approx((3 * 100 / 4) ** 0.5)
    # the heavier metric matters more
    assert distance({"a": 50, "b": 50}, {"a": 70, "b": 50}, w) > distance({"a": 50, "b": 50}, {"a": 50, "b": 70}, w)
    assert distance({"a": 10}, {"a": 90}, {"a": 1}) == pytest.approx(80)


def test_too_few_shared_metrics_means_no_comparison():
    w = {"a": 1.0, "b": 1.0, "c": 1.0}
    assert 2 / 3 >= MIN_SHARED_WEIGHT  # two of three equal metrics is enough
    assert distance({"a": 1, "b": 1}, {"a": 1, "b": 1, "c": 1}, w) is not None
    assert distance({"a": 1}, {"a": 1, "b": 1}, w) is None


def test_differences_name_notable_strengths_and_weaknesses():
    from app.scoring import model_v1 as M
    cb = M.WEIGHTS["CB"]
    keys = list(cb)
    target = {k: 50.0 for k in keys}
    other = {**target, keys[0]: 80.0, keys[1]: 20.0, keys[2]: 55.0}
    stronger, weaker = differences(target, other, cb)
    assert [d["diff"] for d in stronger] == [30.0] and [d["diff"] for d in weaker] == [-30.0]
    assert stronger[0]["metric"].startswith(M.METRICS[keys[0]].label)


def test_lower_is_better_metrics_say_which_way():
    from app.scoring import model_v1 as M
    lower = next(k for k in M.WEIGHTS["CB"] if M.METRICS[k].lower_is_better)
    stronger, _ = differences({lower: 20.0}, {lower: 80.0}, {lower: 1.0})
    _, weaker = differences({lower: 80.0}, {lower: 20.0}, {lower: 1.0})
    assert stronger[0]["metric"].endswith("(fewer)") and weaker[0]["metric"].endswith("(more)")


# --- the endpoint --------------------------------------------------------------------------------

def test_nearest_profiles_come_first(seeded):  # noqa: F811
    c, players, _ = seeded
    r = c.get(f"/api/v1/players/{players[5].id}/similar", params={"include_low": True})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["player"]["player_id"] == players[5].id and body["player"]["role"] == "CB"
    ids = [x["player_id"] for x in body["results"]]
    assert players[5].id not in ids and set(ids[:2]) == {players[4].id, players[6].id}
    sims = [x["similarity"] for x in body["results"]]
    assert sims == sorted(sims, reverse=True) and all(0 <= s <= 100 for s in sims)
    assert body["metrics"] and body["candidates"] == 11


def test_filters_and_exclusions(seeded):  # noqa: F811
    c, players, _ = seeded
    url = f"/api/v1/players/{players[5].id}/similar"
    cheap = c.get(url, params={"include_low": True, "max_price_eur": 4_000_000}).json()["results"]
    assert cheap and all(x["price_eur"] <= 4_000_000 for x in cheap)
    out = c.get(url, params={"include_low": True, "exclude_id": [players[4].id, players[6].id], "limit": 3}).json()
    ids = [x["player_id"] for x in out["results"]]
    assert len(ids) == 3 and players[4].id not in ids and players[6].id not in ids
    assert c.get(url, params={"include_low": True, "league_id": 999999}).json()["results"] == []


def test_unknown_or_unscored_player_is_404(seeded):  # noqa: F811
    c, _, _ = seeded
    assert c.get("/api/v1/players/99999999/similar").status_code == 404
    assert c.get("/api/v1/players/1/similar", params={"limit": 0}).status_code == 422


def test_labels_with_brackets_get_one_direction_note():
    from app.scoring import model_v1 as M
    key = next(k for k, m in M.METRICS.items() if m.lower_is_better and "(" in m.label)
    stronger, _ = differences({key: 20.0}, {key: 80.0}, {key: 1.0})
    assert stronger[0]["metric"].count("(") == 1 and stronger[0]["metric"].endswith("(fewer)")
