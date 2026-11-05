"""Versioned scoring models and the scores they produce (calculated data)."""

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, SmallInteger, String, Text, UniqueConstraint, func
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
    role: Mapped[str] = mapped_column(String(2), index=True)  # GK, CB, FB, CM, AW, ST
    position_group: Mapped[str] = mapped_column(String(3))
    score_within_league: Mapped[float] = mapped_column(Float)  # 0-100
    score_adjusted: Mapped[float | None] = mapped_column(Float)  # 0-100, league-strength adjusted
    value_for_money: Mapped[float | None] = mapped_column(Float)
    reliability: Mapped[str] = mapped_column(String(10))  # high / medium / low
    breakdown: Mapped[dict | None] = mapped_column(JSON)  # per-metric percentiles, for explanations
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class StatFieldCoverage(Base):
    """Per league, season, role and field: is the field recorded? (coverage rule, methodology section 3)"""

    __tablename__ = "stat_field_coverage"
    __table_args__ = (UniqueConstraint("model_id", "league_id", "season", "role", "field"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    model_id: Mapped[int] = mapped_column(ForeignKey("scoring_model.id"))
    league_id: Mapped[int] = mapped_column(ForeignKey("league.id"))
    season: Mapped[int] = mapped_column(SmallInteger)
    role: Mapped[str] = mapped_column(String(2))
    field: Mapped[str] = mapped_column(String(40))
    regulars: Mapped[int] = mapped_column(Integer)
    coverage: Mapped[float] = mapped_column(Float)
    recorded: Mapped[bool] = mapped_column(Boolean)


class LeagueAdjustment(Base):
    """Result of the league-strength calibration for a model and season, including the decision."""

    __tablename__ = "league_adjustment"
    __table_args__ = (UniqueConstraint("model_id", "season"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    model_id: Mapped[int] = mapped_column(ForeignKey("scoring_model.id"))
    season: Mapped[int] = mapped_column(SmallInteger)
    beta: Mapped[float | None] = mapped_column(Float)  # probit units per 100 Elo
    alpha: Mapped[float | None] = mapped_column(Float)
    ci_low: Mapped[float | None] = mapped_column(Float)
    ci_high: Mapped[float | None] = mapped_column(Float)
    n_movers: Mapped[int] = mapped_column(Integer)
    n_stayers: Mapped[int] = mapped_column(Integer)
    accepted: Mapped[bool] = mapped_column(Boolean)
    reason: Mapped[str] = mapped_column(Text)
    e_ref: Mapped[float | None] = mapped_column(Float)
    details: Mapped[dict | None] = mapped_column(JSON)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
