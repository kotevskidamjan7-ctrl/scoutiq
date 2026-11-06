"""Optional language-model parser (FR-15): used only when ANTHROPIC_API_KEY is set.

The model sees the request and the list of leagues, and must answer by calling one tool whose input
is exactly AssistantFilters. The answer is validated like user input; any failure (no key, no credit,
network, invalid output) raises LLMUnavailable and the caller falls back to the rule-based parser.
The model never sees the database and never chooses players.
"""

import httpx
from pydantic import ValidationError

from app.assistant.filters import LEAGUE_CODES, AssistantFilters

API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"
TIMEOUT_S = 20.0

LEAGUE_NAMES = {"GB1": "Premier League (England)", "ES1": "La Liga (Spain)", "IT1": "Serie A (Italy)",
                "L1": "Bundesliga (Germany)", "FR1": "Ligue 1 (France)", "PO1": "Primeira Liga (Portugal)",
                "NL1": "Eredivisie (Netherlands)", "BE1": "Pro League (Belgium)", "TR1": "Süper Lig (Türkiye)",
                "A1": "Bundesliga (Austria)", "C1": "Super League (Switzerland)", "PL1": "Ekstraklasa (Poland)",
                "KR1": "HNL (Croatia)", "SER1": "SuperLiga (Serbia)"}

SYSTEM = """You turn a football scout's request into search filters for a scouting app. Reply only by calling
the set_filters tool. Rules:
- Positions: GK goalkeeper, CB centre-back, FB full-back or wing-back, CM any central midfielder (defensive,
  box-to-box, attacking/number 10), AW winger or wide forward, ST striker/centre-forward. "Defender" means CB and FB.
- role_counts only when the request says how many ("two centre-backs"); a single "a striker" is ST: 1 only if
  other positions in the same request have numbers.
- max_price_eur is the most for ONE player ("under 2m", "max 5 million"); budget_eur is the TOTAL to spend
  ("budget", "in total"). Amounts in euros as integers.
- Ages: "under 25" means age_max 24, "25 or younger"/"up to 25" means 25, "over 30" means age_min 31.
  "Young" without a number means age_max 23; "experienced" means age_min 29.
- leagues: where the player plays now, as competition codes: {leagues}. A country that hosts one of these
  leagues ("from Belgium", "in Spain") means its league. Nationality adjectives ("Spanish striker",
  "Macedonian") mean nationalities, using English country names as on Transfermarkt (e.g. "North Macedonia").
- still_playing true for "still playing", "plays regularly", "active".
- Leave out anything not asked for. Do not guess. The request may be in English or Macedonian."""


class LLMUnavailable(Exception):
    """The language model could not produce valid filters; use the rule-based parser instead."""


def _tool_schema() -> dict:
    schema = AssistantFilters.model_json_schema()
    schema.pop("title", None)
    return schema


CONTEXT = {
    "price": "The user is searching a player list: an amount with no other word means max_price_eur.",
    "budget": "The user is building or improving a squad: an amount with no other word means budget_eur.",
}


def parse(text: str, api_key: str, model: str, bare_amount: str = "price") -> AssistantFilters:
    leagues = ", ".join(f"{c} = {LEAGUE_NAMES.get(c, c)}" for c in LEAGUE_CODES)
    body = {
        "model": model,
        "max_tokens": 400,
        "system": SYSTEM.format(leagues=leagues) + "\n- " + CONTEXT[bare_amount],
        "tools": [{"name": "set_filters", "description": "Set the search filters.", "input_schema": _tool_schema()}],
        "tool_choice": {"type": "tool", "name": "set_filters"},
        "messages": [{"role": "user", "content": text}],
    }
    headers = {"x-api-key": api_key, "anthropic-version": API_VERSION, "content-type": "application/json"}
    try:
        r = httpx.post(API_URL, json=body, headers=headers, timeout=TIMEOUT_S)
    except httpx.HTTPError as e:
        raise LLMUnavailable(f"could not reach the AI service ({type(e).__name__})") from e
    if r.status_code != 200:
        try:
            msg = r.json().get("error", {}).get("message", "")
        except ValueError:
            msg = ""
        if "credit" in msg.lower():
            raise LLMUnavailable("the AI service account has no credit")
        if r.status_code in (401, 403):
            raise LLMUnavailable("the AI service key was not accepted")
        raise LLMUnavailable(f"the AI service answered {r.status_code}")
    try:
        blocks = r.json()["content"]
        call = next(b for b in blocks if b.get("type") == "tool_use" and b.get("name") == "set_filters")
        return AssistantFilters.model_validate(call["input"])
    except (KeyError, StopIteration, ValueError, ValidationError) as e:
        raise LLMUnavailable("the AI answer was not valid filters") from e
