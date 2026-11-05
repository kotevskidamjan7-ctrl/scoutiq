"""Scoring model v1.0: roles, metric definitions and weights.

This file is the single source of truth for the methodology document's tables.
Changing any weight or metric means a new VERSION (old scores stay reproducible).
"""

from dataclasses import dataclass

VERSION = "v1.0"

MIN_SCORED_MINUTES = 450      # below this: not scored
REFERENCE_MINUTES = 900       # reference group for percentiles; optimizer default
HIGH_RELIABILITY_MINUTES = 1800
SHRINK_MINUTES = 450          # m0: per-90 values pulled toward the role mean by 5 average matches
COVERAGE_RECORDED = 0.80      # field counts as recorded in a league-role if >= 80% of regulars have it
MIN_WEIGHT_COVERAGE = 0.70    # less available weight than this -> low reliability
MIN_REFERENCE_PLAYERS = 8     # fewer regulars than this in a league-role -> role not scored there

# Transfermarkt sub-position -> scoring role (verified against the snapshot on 2026-11-05)
ROLE_BY_SUBPOSITION = {
    "Goalkeeper": "GK",
    "Centre-Back": "CB",
    "Left-Back": "FB",
    "Right-Back": "FB",
    "Defensive Midfield": "CM",
    "Central Midfield": "CM",
    "Attacking Midfield": "AW",
    "Left Midfield": "AW",
    "Right Midfield": "AW",
    "Left Winger": "AW",
    "Right Winger": "AW",
    "Centre-Forward": "ST",
    "Second Striker": "ST",
}
ROLES = ("GK", "CB", "FB", "CM", "AW", "ST")

# API-Football's position for the scored season, per role. A mismatch is flagged, not corrected:
# the role comes from the (2026) Transfermarkt profile, the API position from 2024/25 itself.
# The API uses both "Attacker" and "Forward" for the same group.
API_POSITIONS_BY_ROLE = {
    "GK": {"Goalkeeper"},
    "CB": {"Defender"},
    "FB": {"Defender"},
    "CM": {"Midfielder"},
    "AW": {"Midfielder", "Attacker", "Forward"},
    "ST": {"Attacker", "Forward"},
}


def position_check(role: str, api_position: str | None) -> dict:
    if not api_position:
        return {"api_position": None, "consistent": None}
    return {"api_position": api_position, "consistent": api_position in API_POSITIONS_BY_ROLE[role]}


@dataclass(frozen=True)
class Metric:
    """A per-90 count (kind='per90') or a success rate (kind='rate').

    per90: numerator = sum(plus) - sum(minus) fields
    rate:  successes = sum(plus) - sum(minus); attempts = sum(attempts_plus) - sum(attempts_minus)
    required: fields that must be recorded in the league-role for the metric to exist
    optional: fields used if recorded, treated as 0 otherwise (e.g. penalties)
    """

    name: str
    label: str
    kind: str
    plus: tuple[str, ...]
    minus: tuple[str, ...] = ()
    attempts_plus: tuple[str, ...] = ()
    attempts_minus: tuple[str, ...] = ()
    weights_in_sum: tuple[float, ...] | None = None  # multipliers for `plus` (card points)
    k: float = 0.0
    lower_is_better: bool = False
    optional: tuple[str, ...] = ()

    @property
    def required(self) -> tuple[str, ...]:
        fields = set(self.plus) | set(self.minus) | set(self.attempts_plus) | set(self.attempts_minus)
        return tuple(sorted(fields - set(self.optional)))


METRICS = {
    m.name: m
    for m in [
        Metric("npg90", "Non-penalty goals per 90", "per90", plus=("goals",), minus=("penalty_scored",),
               optional=("penalty_scored",)),
        Metric("sot90", "Shots on target per 90", "per90", plus=("shots_on",)),
        Metric("conversion", "Shot conversion (non-penalty)", "rate", plus=("goals",), minus=("penalty_scored",),
               attempts_plus=("shots_total",), attempts_minus=("penalty_scored", "penalty_missed"), k=10,
               optional=("penalty_scored", "penalty_missed")),
        Metric("a90", "Assists per 90", "per90", plus=("assists",)),
        Metric("kp90", "Key passes per 90", "per90", plus=("passes_key",)),
        Metric("duel_rate", "Duel win rate", "rate", plus=("duels_won",), attempts_plus=("duels_total",), k=20),
        Metric("duels_won90", "Duels won per 90", "per90", plus=("duels_won",)),
        Metric("drb90", "Successful dribbles per 90", "per90", plus=("dribbles_success",)),
        Metric("drb_rate", "Dribble success rate", "rate", plus=("dribbles_success",),
               attempts_plus=("dribbles_attempts",), k=10),
        Metric("fd90", "Fouls drawn per 90", "per90", plus=("fouls_drawn",)),
        Metric("fc90", "Fouls committed per 90", "per90", plus=("fouls_committed",), lower_is_better=True),
        Metric("tk90", "Tackles per 90", "per90", plus=("tackles",)),
        Metric("int90", "Interceptions per 90", "per90", plus=("interceptions",)),
        Metric("blk90", "Blocks per 90", "per90", plus=("blocks",)),
        Metric("pas90", "Passes per 90", "per90", plus=("passes_total",)),
        Metric("dp90", "Dribbled past per 90", "per90", plus=("dribbled_past",), lower_is_better=True),
        Metric("cards90", "Card points per 90 (yellow 1, red 3)", "per90",
               plus=("cards_yellow", "cards_red", "cards_yellowred"), weights_in_sum=(1, 3, 3),
               lower_is_better=True, optional=("cards_yellowred",)),
        Metric("save_rate", "Save rate", "rate", plus=("saves",), attempts_plus=("saves", "goals_conceded"), k=20),
        Metric("gc90", "Goals conceded per 90", "per90", plus=("goals_conceded",), lower_is_better=True),
    ]
}

WEIGHTS: dict[str, dict[str, float]] = {
    "ST": {"npg90": 0.30, "conversion": 0.15, "sot90": 0.15, "a90": 0.10, "kp90": 0.10,
           "duel_rate": 0.10, "drb90": 0.05, "fd90": 0.05},
    "AW": {"kp90": 0.20, "a90": 0.15, "npg90": 0.15, "drb90": 0.15, "sot90": 0.10,
           "fd90": 0.10, "duels_won90": 0.10, "drb_rate": 0.05},
    "CM": {"tk90": 0.15, "int90": 0.15, "pas90": 0.15, "kp90": 0.15, "duel_rate": 0.10,
           "a90": 0.10, "npg90": 0.05, "drb90": 0.05, "blk90": 0.05, "fc90": 0.05},
    "FB": {"tk90": 0.15, "int90": 0.15, "kp90": 0.15, "a90": 0.10, "duel_rate": 0.10,
           "pas90": 0.10, "drb90": 0.10, "blk90": 0.05, "dp90": 0.05, "fc90": 0.05},
    "CB": {"int90": 0.20, "duel_rate": 0.20, "tk90": 0.15, "blk90": 0.15, "duels_won90": 0.10,
           "pas90": 0.10, "dp90": 0.05, "cards90": 0.05},
    "GK": {"save_rate": 0.55, "gc90": 0.30, "pas90": 0.15},
}


def model_definition() -> dict:
    """What is stored in scoring_model.weights: enough to reproduce the scores."""
    return {
        "weights": WEIGHTS,
        "roles": ROLE_BY_SUBPOSITION,
        "parameters": {
            "min_scored_minutes": MIN_SCORED_MINUTES,
            "reference_minutes": REFERENCE_MINUTES,
            "high_reliability_minutes": HIGH_RELIABILITY_MINUTES,
            "shrink_minutes": SHRINK_MINUTES,
            "coverage_recorded": COVERAGE_RECORDED,
            "min_weight_coverage": MIN_WEIGHT_COVERAGE,
            "min_reference_players": MIN_REFERENCE_PLAYERS,
        },
        "metrics": {
            n: {"kind": m.kind, "k": m.k, "lower_is_better": m.lower_is_better, "required": list(m.required)}
            for n, m in METRICS.items()
        },
    }
