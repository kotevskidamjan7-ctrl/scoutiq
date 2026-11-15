"""Shortlist schemas: players a user follows, with notes."""

from datetime import datetime

from pydantic import BaseModel, Field


class ShortlistUpdate(BaseModel):
    note: str | None = Field(None, max_length=2000, description="Private note; omit to keep the current one")


class ShortlistItem(BaseModel):
    player_id: int
    name: str
    age: int | None
    nationality: str | None
    role: str | None
    league_id: int | None
    league: str | None
    club: str | None
    score: float | None
    score_adjusted: float | None
    value_for_money: float | None
    reliability: str | None
    minutes: int | None
    minutes_next: int | None
    price_eur: int | None
    note: str
    added_at: datetime
    value_at_add_eur: int | None
    value_change_pct: float | None = Field(None, description="Market value now vs when added, in %")
