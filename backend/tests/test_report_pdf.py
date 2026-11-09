"""Helpers of the PDF report (no database)."""

from app.reports.pdf import _register_fonts, eur, fit, replacements, requirement_lines, signed


def test_money_and_signs():
    assert eur(65_000_000) == "€65m" and eur(7_300_000) == "€7.3m" and eur(2_000_000) == "€2m"
    assert eur(450_000) == "€450k" and eur(None) == "–"
    assert signed(22.34) == "+22.3" and signed(-3) == "-3.0" and signed(0) == "0.0"


def test_fit_shortens_with_an_ellipsis():
    _register_fonts()
    assert fit("Kostić", "Archivo", 9, 200) == "Kostić"
    short = fit("Konstantinos Mavropanos Papadopoulos", "Archivo", 9, 60)
    assert short.endswith("…") and len(short) < 20


def test_replacements_match_the_site_rule():
    current = [{"player_id": 1, "role": "CB", "score": 70, "name": "A"},
               {"player_id": 2, "role": "CB", "score": 60, "name": "B"},
               {"player_id": 3, "role": "ST", "score": 50, "name": "C"}]
    nxt = [{"player_id": 1, "role": "CB", "score": 70},
           {"player_id": 9, "role": "CB", "score": 90, "signing": True},
           {"player_id": 3, "role": "ST", "score": 50},
           {"player_id": 8, "role": "AW", "score": 80, "signing": True}]
    out = replacements(current, nxt)
    assert out[9]["name"] == "B" and out[8] is None


def test_requirement_lines_in_plain_words():
    req = {"formation": "4-3-3", "budget_eur": 10_000_000, "max_signings": 2, "signing_roles": ["ST"],
           "locked_player_ids": [1], "left_player_ids": [2, 3], "age_max": 24, "league_ids": [5],
           "min_minutes": 900, "min_minutes_next": 0, "score": "adjusted"}
    lines = requirement_lines(req, "improve", {5: "Super liga Srbije"})
    assert lines[0] == "Formation 4-3-3, budget €10m"
    assert "Signings only as: striker" in lines and "Age 24 or younger" in lines
    assert "Leagues: Super liga Srbije" in lines and "2 player(s) marked as having left" in lines
    assert "At least 900 league minutes in 2024/25" in lines and lines[-1] == "Scores adjusted for league strength"
