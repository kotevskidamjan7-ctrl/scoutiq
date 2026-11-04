"""Versioned scoring models and the scores they produce (calculated data)."""

from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, SmallInteger, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ScoringModel(Base):
    """A frozen set of weights and thresholds; changing weights = a new version."""

    __tablename__ = "scoring_model"

    id: Mapped[int] = mapped_column(primary_key=True)
    version: Mapped[str] = mapped_column(String(20), unique=True)
    weights: Mapped[dict] = mapped_column(JSON)
    min_minutes: Mapped[int] = mapped_column(Integer)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ScoutingScore(Base):
    __tablename__ = "scouting_score"
    __table_args__ = (UniqueConstraint("player_id", "model_id", "season", "league_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("player.id", ondelete="CASCADE"), index=True)
    model_id: Mapped[int] = mapped_column(ForeignKey("scoring_model.id"))
    league_id: Mapped[int] = mapped_column(ForeignKey("league.id"))
    season: Mapped[int] = mapped_column(SmallInteger)
    position_group: Mapped[str] = mapped_column(String(3))
    score_within_league: Mapped[float] = mapped_column(Float)  # 0-100
    score_adjusted: Mapped[float | None] = mapped_column(Float)  # 0-100, league-strength adjusted
    value_for_money: Mapped[float | None] = mapped_column(Float)
    reliability: Mapped[str] = mapped_column(String(10))  # high / medium / low
    breakdown: Mapped[dict | None] = mapped_column(JSON)  # per-metric percentiles, for explanations
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
