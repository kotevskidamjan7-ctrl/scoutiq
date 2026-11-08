"""Tests for the API-Football client (no real HTTP) and club matching."""

import pytest

from ingestion.api_football import club_key, fetch, match_clubs
from ingestion.api_football_client import ApiFootballClient, BudgetExhausted, PlanRestricted, ServerUnavailable


class FakeResponse:
    def __init__(self, body, status=200, remaining=50):
        self._body = body
        self.status_code = status
        self.headers = {"x-ratelimit-requests-remaining": str(remaining)}

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400 and self.status_code != 429:
            raise RuntimeError(self.status_code)


class FakeSession:
    """Returns queued responses and records every call."""

    def __init__(self, responder):
        self.responder = responder
        self.calls = []

    def get(self, url, headers, params, timeout):
        self.calls.append((url.rsplit("/", 1)[-1], dict(params)))
        return self.responder(url.rsplit("/", 1)[-1], params)


def make_client(tmp_path, responder, **kw):
    session = FakeSession(responder)
    client = ApiFootballClient("test-key", tmp_path, session=session, sleep=lambda s: None, min_interval_s=0, **kw)
    return client, session


def ok(body, remaining=50):
    return FakeResponse({"errors": [], **body}, remaining=remaining)


# ---------- client ----------

def test_cached_response_is_never_requested_twice(tmp_path):
    client, session = make_client(tmp_path, lambda e, p: ok({"response": [1]}))
    assert client.get("teams", {"league": 39, "season": 2024}) == {"errors": [], "response": [1]}
    client.get("teams", {"league": 39, "season": 2024})
    assert len(session.calls) == 1
    assert client.live_requests == 1


def test_run_cap_stops_before_the_request(tmp_path):
    client, session = make_client(tmp_path, lambda e, p: ok({}), max_requests=2)
    client.get("a", {"x": 1})
    client.get("a", {"x": 2})
    with pytest.raises(BudgetExhausted):
        client.get("a", {"x": 3})
    assert len(session.calls) == 2


def test_low_daily_quota_stops(tmp_path):
    client, _ = make_client(tmp_path, lambda e, p: ok({}, remaining=5), reserve=5)
    client.get("a", {"x": 1})
    with pytest.raises(BudgetExhausted):
        client.get("a", {"x": 2})


def test_daily_limit_error_stops_and_is_not_cached(tmp_path):
    client, _ = make_client(
        tmp_path, lambda e, p: FakeResponse({"errors": {"requests": "You have reached the request limit for the day"}})
    )
    with pytest.raises(BudgetExhausted):
        client.get("a", {"x": 1})
    assert client.cached("a", {"x": 1}) is None


def test_plan_restriction_is_reported(tmp_path):
    client, _ = make_client(
        tmp_path,
        lambda e, p: FakeResponse({"errors": {"plan": "Free plans are limited to a maximum value of 3 for the Page parameter"}}),
    )
    with pytest.raises(PlanRestricted):
        client.get("players", {"team": 33, "season": 2024, "page": 4})


def test_rate_limit_waits_and_retries_once(tmp_path):
    answers = iter([FakeResponse({}, status=429), ok({"response": ["fine"]})])
    slept = []
    session = FakeSession(lambda e, p: next(answers))
    client = ApiFootballClient("k", tmp_path, session=session, sleep=slept.append, min_interval_s=0)
    assert client.get("a", {"x": 1})["response"] == ["fine"]
    assert 61 in slept


def test_server_error_is_retried_then_succeeds(tmp_path):
    """Found on real data (2026-11-08): API-Football answered 500 for teams?league=94."""
    answers = iter([FakeResponse({}, status=500), ok({"response": ["fine"]})])
    slept = []
    session = FakeSession(lambda e, p: next(answers))
    client = ApiFootballClient("k", tmp_path, session=session, sleep=slept.append, min_interval_s=0)
    assert client.get("teams", {"league": 94})["response"] == ["fine"]
    assert slept == [10] and client.live_requests == 2


def test_persistent_server_error_stops_with_a_clear_exception(tmp_path):
    session = FakeSession(lambda e, p: FakeResponse({}, status=500))
    slept = []
    client = ApiFootballClient("k", tmp_path, session=session, sleep=slept.append, min_interval_s=0)
    with pytest.raises(ServerUnavailable, match="500 3 times"):
        client.get("teams", {"league": 94})
    assert slept == [10, 30] and len(session.calls) == 3
    assert client.cached("teams", {"league": 94}) is None      # a failure is never cached


def test_server_retries_respect_the_run_cap(tmp_path):
    session = FakeSession(lambda e, p: FakeResponse({}, status=503))
    client = ApiFootballClient("k", tmp_path, session=session, sleep=lambda s: None, min_interval_s=0, max_requests=2)
    with pytest.raises(BudgetExhausted):
        client.get("teams", {"league": 94})
    assert len(session.calls) == 2


# ---------- fetch flow ----------

class _League:
    def __init__(self, name, af_id):
        self.name, self.apifootball_id = name, af_id


def test_fetch_requests_at_most_three_pages_and_reports_truncation(tmp_path):
    def responder(endpoint, params):
        if endpoint == "teams":
            return ok({"response": [{"team": {"id": 1, "name": "Big Club"}}, {"team": {"id": 2, "name": "Small Club"}}]})
        total = 4 if params["team"] == 1 else 2
        return ok({"paging": {"current": params["page"], "total": total}, "response": []})

    client, session = make_client(tmp_path, responder)
    progress = fetch(client, [_League("Test League", 39)], 2024)

    pages_requested = sorted((p["team"], p["page"]) for e, p in session.calls if e == "players")
    assert pages_requested == [(1, 1), (1, 2), (1, 3), (2, 1), (2, 2)]  # never page 4
    assert progress.teams_complete == 2
    assert progress.truncated == [("Test League", "Big Club", 4)]


def test_fetch_resumes_from_cache_after_stopping(tmp_path):
    def responder(endpoint, params):
        if endpoint == "teams":
            return ok({"response": [{"team": {"id": t, "name": f"T{t}"}} for t in (1, 2, 3)]})
        return ok({"paging": {"total": 1}, "response": []})

    client, _ = make_client(tmp_path, responder, max_requests=2)  # teams + 1 team page, then stop
    with pytest.raises(BudgetExhausted):
        fetch(client, [_League("L", 39)], 2024)

    client2, session2 = make_client(tmp_path, responder)  # "next day"
    progress = fetch(client2, [_League("L", 39)], 2024)
    assert progress.teams_complete == 3
    assert len(session2.calls) == 2  # only the two teams not fetched yesterday


# ---------- club matching ----------

def test_club_key_strips_legal_and_generic_words():
    assert club_key("Futbol Club Barcelona") == "barcelona"
    assert club_key("Ballspielverein Borussia 09 e.V. Dortmund") == "borussia dortmund"
    assert club_key("Verein für Bewegungsspiele Stuttgart 1893") == "stuttgart"


def test_matching_is_one_to_one_and_uses_venue_as_evidence():
    api = [
        {"id": 529, "name": "Barcelona", "venue": None},
        {"id": 541, "name": "Real Madrid", "venue": None},
        {"id": 530, "name": "Atletico Madrid", "venue": None},
        {"id": 505, "name": "Inter", "venue": "Stadio Giuseppe Meazza"},
        {"id": 489, "name": "AC Milan", "venue": "Stadio Giuseppe Meazza"},
    ]
    tm = [
        {"club_id": 1, "name": "Futbol Club Barcelona", "venue": None},
        {"club_id": 2, "name": "Real Madrid Club de Fútbol", "venue": None},
        {"club_id": 3, "name": "Club Atlético de Madrid S.A.D.", "venue": None},
        {"club_id": 4, "name": "Football Club Internazionale Milano S.p.A.", "venue": "Giuseppe Meazza"},
        {"club_id": 5, "name": "Associazione Calcio Milan", "venue": "Giuseppe Meazza"},
    ]
    matches, unmatched = match_clubs(api, tm)
    pairs = {a["id"]: t["club_id"] for a, t, _ in matches}
    assert pairs == {529: 1, 541: 2, 530: 3, 505: 4, 489: 5}
    assert unmatched == []


def test_no_match_below_threshold():
    matches, unmatched = match_clubs([{"id": 1, "name": "Arsenal"}], [{"club_id": 9, "name": "Chelsea Football Club"}])
    assert matches == [] and unmatched[0]["id"] == 1


# ---------- enable-league ----------

from ingestion.api_football import check_league_response  # noqa: E402


class _L:
    def __init__(self, country):
        self.country = country


def _league_body(country="Portugal", players=True, year=2024, kind="League"):
    # same shape as the real /leagues response seen in Phase 1b (league, country, seasons[].coverage)
    return {"errors": [], "response": [{
        "league": {"id": 94, "name": "Primeira Liga", "type": kind},
        "country": {"name": country},
        "seasons": [{"year": year, "coverage": {"players": players, "fixtures": {"statistics_players": players}}}],
    }]}


def test_league_check_accepts_matching_league():
    problems, info = check_league_response(_league_body(), _L("Portugal"), 2024)
    assert problems == [] and info["name"] == "Primeira Liga"


def test_league_check_refuses_wrong_country_cup_or_missing_coverage():
    assert check_league_response(_league_body(country="Brazil"), _L("Portugal"), 2024)[0]
    assert check_league_response(_league_body(kind="Cup"), _L("Portugal"), 2024)[0]
    assert check_league_response(_league_body(players=False), _L("Portugal"), 2024)[0]
    assert check_league_response(_league_body(year=2023), _L("Portugal"), 2024)[0]
    assert check_league_response({"response": []}, _L("Portugal"), 2024)[0]


def test_turkiye_matches_turkey():
    assert check_league_response(_league_body(country="Turkey"), _L("Türkiye"), 2024)[0] == []


# --- club matching: names sharing a word ("Real ...") -----------------------------------------
from ingestion.api_football import club_similarity, plan_links  # noqa: E402

REAL_API = [{"id": 541, "name": "Real Madrid"}, {"id": 543, "name": "Real Betis"},
            {"id": 548, "name": "Real Sociedad"}, {"id": 720, "name": "Valladolid"}]
REAL_TM = [  # order chosen so a tie would pick the wrong club first
    {"club_id": 26, "name": "Real Betis Balompié S.A.D."},
    {"club_id": 39, "name": "Real Sociedad de Fútbol S.A.D."},
    {"club_id": 61, "name": "Real Valladolid Club de Fútbol"},
    {"club_id": 7, "name": "Real Madrid Club de Fútbol"},
]


def test_real_clubs_are_told_apart():
    matches, unmatched = match_clubs(REAL_API, REAL_TM)
    got = {a["id"]: t["club_id"] for a, t, _ in matches}
    assert got == {541: 7, 543: 26, 548: 39, 720: 61}
    assert unmatched == []


def test_real_sociedad_keeps_its_distinctive_word():
    assert club_key("Real Sociedad de Fútbol S.A.D.") == "real sociedad"
    assert club_similarity("Real Sociedad", "Real Madrid Club de Fútbol") < 70


def test_existing_links_are_kept_unless_remap():
    matches, _ = match_clubs(REAL_API, REAL_TM)
    existing = {"541": 39, "548": 7}  # old, swapped links
    links, changed, conflicts = plan_links(matches, existing)
    assert "541" not in links and "548" not in links
    assert {str(a["id"]) for a, _, _ in changed} == {"541", "548"}
    # nothing written may give a club to two teams
    final = {**existing, **links}
    assert len(set(final.values())) == len(final)


def test_remap_can_swap_links_without_clashing():
    matches, _ = match_clubs(REAL_API, REAL_TM)
    links, _, conflicts = plan_links(matches, {"541": 39, "548": 7}, remap=True)
    assert links["541"] == 7 and links["548"] == 39 and conflicts == []


def test_club_linked_to_another_team_is_not_taken():
    matches, _ = match_clubs([{"id": 1, "name": "Real Madrid"}], REAL_TM)
    links, _, conflicts = plan_links(matches, {"999": 7}, remap=True)
    assert links == {} and len(conflicts) == 1
