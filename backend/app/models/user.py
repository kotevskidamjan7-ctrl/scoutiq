"""Users and their saved optimization scenarios."""

from datetime import datetime

from sqlalchemy import JSON, Boolean, CheckConstraint, DateTime, Float, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

ROLES = ("scout", "admin")
MODES = ("build", "improve")


class AppUser(Base):
    __tablename__ = "app_user"
    __table_args__ = (CheckConstraint(f"role IN {ROLES}", name="role"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(10), default="scout")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    scenarios: Mapped[list["Scenario"]] = relationship(back_populates="user")


class Scenario(Base):
    """A saved Mode A (build) or Mode B (improve) run: inputs, result and solver stats."""

    __tablename__ = "scenario"
    __table_args__ = (CheckConstraint(f"mode IN {MODES}", name="mode"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    mode: Mapped[str] = mapped_column(String(10))
    constraints: Mapped[dict] = mapped_column(JSON)
    result_summary: Mapped[dict | None] = mapped_column(JSON)
    solve_time_ms: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped[AppUser] = relationship(back_populates="scenarios")
    players: Mapped[list["ScenarioPlayer"]] = relationship(back_populates="scenario", cascade="all, delete-orphan")


class ScenarioPlayer(Base):
    __tablename__ = "scenario_player"

    scenario_id: Mapped[int] = mapped_column(ForeignKey("scenario.id", ondelete="CASCADE"), primary_key=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("player.id"), primary_key=True)
    slot: Mapped[str] = mapped_column(String(10))  # e.g. "GK", "LCB", "ST"
    is_existing: Mapped[bool] = mapped_column(Boolean, default=False)  # True = already in squad (Mode B)

    scenario: Mapped[Scenario] = relationship(back_populates="players")
