"""Players, their IDs in each source, season stats and market valuations.

Rules enforced by the schema:
  * Stats are stored per player, club, league, season and source - never merged.
  * Every stat column is nullable: NULL means "not provided", never zero.
  * Valuations carry a type, so Transfermarkt values, model estimates and
    user-entered prices can never be confused.
"""

from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

VALUATION_TYPES = ("transfermarkt", "model_estimate", "user_input")
POSITION_GROUPS = ("GK", "DEF", "MID", "FWD")


class Player(TimestampMixin, Base):
    """One canonical real person, linked to records in every source."""

    __tablename__ = "player"

    id: Mapped[int] = mapped_column(primary_key=True)
    full_name: Mapped[str] = mapped_column(String(120))
    name_normalized: Mapped[str] = mapped_column(String(120), index=True)
    birth_date: Mapped[date | None] = mapped_column(Date, index=True)
    nationality: Mapped[str | None] = mapped_column(String(60))
    foot: Mapped[str | None] = mapped_column(String(10))
    height_cm: Mapped[int | None] = mapped_column(SmallInteger)
    position_group: Mapped[str | None] = mapped_column(String(3))  # GK/DEF/MID/FWD
    primary_position: Mapped[str | None] = mapped_column(String(40))  # e.g. "Centre-Back"
    secondary_position: Mapped[str | None] = mapped_column(String(40))

    source_ids: Mapped[list["PlayerSourceId"]] = relationship(back_populates="player")
    season_stats: Mapped[list["PlayerSeasonStats"]] = relationship(back_populates="player")
    valuations: Mapped[list["MarketValuation"]] = relationship(back_populates="player")

    __table_args__ = (
        CheckConstraint(
            f"position_group IS NULL OR position_group IN {POSITION_GROUPS}", name="position_group"
        ),
    )


class PlayerSourceId(Base):
    """How a source record was linked to a canonical player, and how confident we are."""

    __tablename__ = "player_source_id"
    __table_args__ = (UniqueConstraint("player_id", "source_id"),)

    source_id: Mapped[int] = mapped_column(ForeignKey("data_source.id"), primary_key=True)
    external_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("player.id", ondelete="CASCADE"), index=True)
    match_method: Mapped[str] = mapped_column(String(30))  # source_primary / exact / fuzzy / manual
    match_confidence: Mapped[float] = mapped_column(Float, default=1.0)

    player: Mapped[Player] = relationship(back_populates="source_ids")


class LinkCandidate(Base):
    """Uncertain matches waiting for manual review (never auto-linked)."""

    __tablename__ = "link_candidate"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("data_source.id"))
    external_id: Mapped[str] = mapped_column(String(40))
    external_name: Mapped[str] = mapped_column(String(120))
    candidate_player_id: Mapped[int | None] = mapped_column(ForeignKey("player.id", ondelete="CASCADE"))
    similarity: Mapped[float | None] = mapped_column(Float)
    reason: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending/accepted/rejected
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PlayerSeasonStats(Base):
    """Season aggregates for one player at one club in one competition, from one source."""

    __tablename__ = "player_season_stats"
    __table_args__ = (UniqueConstraint("player_id", "club_id", "league_id", "season", "source_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("player.id", ondelete="CASCADE"), index=True)
    club_id: Mapped[int] = mapped_column(ForeignKey("club.id"))
    league_id: Mapped[int] = mapped_column(ForeignKey("league.id"))
    season: Mapped[int] = mapped_column(SmallInteger, index=True)  # 2024 = 2024/25
    source_id: Mapped[int] = mapped_column(ForeignKey("data_source.id"))
    import_run_id: Mapped[int | None] = mapped_column(ForeignKey("import_run.id"))

    # games
    position_reported: Mapped[str | None] = mapped_column(String(20))
    appearances: Mapped[int | None] = mapped_column(SmallInteger)
    lineups: Mapped[int | None] = mapped_column(SmallInteger)
    minutes: Mapped[int | None] = mapped_column(Integer)
    rating: Mapped[float | None] = mapped_column(Float)
    # attacking
    goals: Mapped[int | None] = mapped_column(SmallInteger)
    assists: Mapped[int | None] = mapped_column(SmallInteger)
    shots_total: Mapped[int | None] = mapped_column(SmallInteger)
    shots_on: Mapped[int | None] = mapped_column(SmallInteger)
    # passing
    passes_total: Mapped[int | None] = mapped_column(Integer)
    passes_key: Mapped[int | None] = mapped_column(SmallInteger)
    pass_accuracy: Mapped[float | None] = mapped_column(Float)
    # defending
    tackles: Mapped[int | None] = mapped_column(SmallInteger)
    blocks: Mapped[int | None] = mapped_column(SmallInteger)
    interceptions: Mapped[int | None] = mapped_column(SmallInteger)
    duels_total: Mapped[int | None] = mapped_column(SmallInteger)
    duels_won: Mapped[int | None] = mapped_column(SmallInteger)
    # dribbling
    dribbles_attempts: Mapped[int | None] = mapped_column(SmallInteger)
    dribbles_success: Mapped[int | None] = mapped_column(SmallInteger)
    dribbled_past: Mapped[int | None] = mapped_column(SmallInteger)
    # discipline
    fouls_drawn: Mapped[int | None] = mapped_column(SmallInteger)
    fouls_committed: Mapped[int | None] = mapped_column(SmallInteger)
    cards_yellow: Mapped[int | None] = mapped_column(SmallInteger)
    cards_yellowred: Mapped[int | None] = mapped_column(SmallInteger)
    cards_red: Mapped[int | None] = mapped_column(SmallInteger)
    # penalties
    penalty_won: Mapped[int | None] = mapped_column(SmallInteger)
    penalty_committed: Mapped[int | None] = mapped_column(SmallInteger)
    penalty_scored: Mapped[int | None] = mapped_column(SmallInteger)
    penalty_missed: Mapped[int | None] = mapped_column(SmallInteger)
    penalty_saved: Mapped[int | None] = mapped_column(SmallInteger)
    # goalkeeping
    saves: Mapped[int | None] = mapped_column(SmallInteger)
    goals_conceded: Mapped[int | None] = mapped_column(SmallInteger)

    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    player: Mapped[Player] = relationship(back_populates="season_stats")


class MarketValuation(Base):
    """An estimated market value at a date. Not a transfer fee, not proof of availability."""

    __tablename__ = "market_valuation"
    __table_args__ = (
        UniqueConstraint("player_id", "valuation_date", "valuation_type", "source_id"),
        CheckConstraint(f"valuation_type IN {VALUATION_TYPES}", name="valuation_type"),
        CheckConstraint("value_eur >= 0", name="value_non_negative"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("player.id", ondelete="CASCADE"), index=True)
    value_eur: Mapped[int] = mapped_column(BigInteger)
    valuation_date: Mapped[date] = mapped_column(Date)
    valuation_type: Mapped[str] = mapped_column(String(20))
    source_id: Mapped[int | None] = mapped_column(ForeignKey("data_source.id"))
    club_id: Mapped[int | None] = mapped_column(ForeignKey("club.id"))  # club at valuation time
    error_band_eur: Mapped[int | None] = mapped_column(BigInteger)  # only for model estimates

    player: Mapped[Player] = relationship(back_populates="valuations")
