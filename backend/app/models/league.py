"""Leagues, clubs, league strength, and club identifiers in each source."""

from datetime import date

from sqlalchemy import Boolean, Date, Float, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class League(Base):
    """A supported competition. Adding a league = adding a row here (NFR-10)."""

    __tablename__ = "league"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    country: Mapped[str] = mapped_column(String(60))
    tm_competition_id: Mapped[str | None] = mapped_column(String(10), unique=True)  # e.g. "GB1"
    apifootball_id: Mapped[int | None] = mapped_column(unique=True)  # e.g. 39
    rollout_stage: Mapped[str] = mapped_column(String(10))  # "v1", "v1.5", "v2"
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)

    clubs: Mapped[list["Club"]] = relationship(back_populates="league")


class LeagueStrength(Base):
    """League-strength input for cross-league adjustment (from ClubElo)."""

    __tablename__ = "league_strength"
    __table_args__ = (UniqueConstraint("league_id", "as_of_date", "method"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    league_id: Mapped[int] = mapped_column(ForeignKey("league.id"))
    as_of_date: Mapped[date] = mapped_column(Date)
    mean_club_elo: Mapped[float] = mapped_column(Float)
    method: Mapped[str] = mapped_column(String(50), default="mean_club_elo")


class Club(Base):
    __tablename__ = "club"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    country: Mapped[str | None] = mapped_column(String(60))
    league_id: Mapped[int | None] = mapped_column(ForeignKey("league.id"))

    league: Mapped[League | None] = relationship(back_populates="clubs")


class ClubSourceId(Base):
    """The same club's ID in each external source (API-Football team id, Transfermarkt club id)."""

    __tablename__ = "club_source_id"
    __table_args__ = (UniqueConstraint("club_id", "source_id"),)

    source_id: Mapped[int] = mapped_column(ForeignKey("data_source.id"), primary_key=True)
    external_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    club_id: Mapped[int] = mapped_column(ForeignKey("club.id", ondelete="CASCADE"))
