"""Responses for the explorer, the player profile and the comparison."""

from datetime import date
from typing import Literal

from pydantic import BaseModel


class LeagueOut(BaseModel):
    id: int
    name: str
    country: str
    scored_players: int


class PlayerRowOut(BaseModel):
    player_id: int
    name: str
    age: int | None
    nationality: str | None
    role: str
    league_id: int
    league: str
    club: str
    score: float
    score_adjusted: float | None
    value_for_money: float | None
    reliability: str
    minutes: int
    minutes_next: int
    price_eur: int | None
    valuation_date: str | None
    position_consistent: bool | None


class PlayerPage(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[PlayerRowOut]


class MetricOut(BaseModel):
    key: str
    label: str
    kind: Literal["per90", "rate"]
    lower_is_better: bool
    value: float | None
    percentile: float | None
    weight: float | None


class ScoreOut(BaseModel):
    season: int
    league_id: int
    league: str
    role: str
    score: float
    score_adjusted: float | None
    value_for_money: float | None
    value_for_money_note: str | None
    reliability: str
    minutes: int | None
    weight_coverage: float | None
    dropped_metrics: list[str]
    position_check: dict | None
    metrics: list[MetricOut]


class MarketValueOut(BaseModel):
    value_eur: int
    valuation_date: date
    source: str


class ValuePoint(BaseModel):
    date: date
    value_eur: int


class SeasonStatsOut(BaseModel):
    season: int
    club: str
    league: str
    source: str
    appearances: int | None
    lineups: int | None
    minutes: int | None
    rating: float | None
    goals: int | None
    assists: int | None
    shots_total: int | None
    shots_on: int | None
    passes_total: int | None
    passes_key: int | None
    tackles: int | None
    interceptions: int | None
    blocks: int | None
    duels_total: int | None
    duels_won: int | None
    dribbles_attempts: int | None
    dribbles_success: int | None
    fouls_drawn: int | None
    fouls_committed: int | None
    cards_yellow: int | None
    cards_red: int | None
    saves: int | None
    goals_conceded: int | None
    penalty_scored: int | None
    penalty_missed: int | None


class RecentRow(BaseModel):
    club: str
    league: str
    appearances: int | None
    minutes: int | None
    goals: int | None
    assists: int | None
    cards_yellow: int | None
    cards_red: int | None


class RecentTotals(BaseModel):
    appearances: int
    minutes: int
    goals: int
    assists: int
    cards_yellow: int
    cards_red: int


class RecentFormOut(BaseModel):
    season: int
    source: str
    rows: list[RecentRow]
    totals: RecentTotals | None


class ProfileOut(BaseModel):
    id: int
    name: str
    birth_date: date | None
    age: int | None
    nationality: str | None
    foot: str | None
    height_cm: int | None
    primary_position: str | None
    secondary_position: str | None
    market_value: MarketValueOut | None
    value_history: list[ValuePoint]
    scores: list[ScoreOut]
    season_stats: list[SeasonStatsOut]
    recent_form: RecentFormOut


class CompareOut(BaseModel):
    players: list[ProfileOut]
    same_role: bool
