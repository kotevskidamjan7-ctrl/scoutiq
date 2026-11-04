"""Provenance: where each record came from and which import run loaded it."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class DataSource(Base):
    """An external data provider, e.g. API-Football or Transfermarkt."""

    __tablename__ = "data_source"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)  # e.g. "api_football"
    name: Mapped[str] = mapped_column(String(100))
    url: Mapped[str | None] = mapped_column(String(255))
    licence_note: Mapped[str | None] = mapped_column(Text)

    import_runs: Mapped[list["ImportRun"]] = relationship(back_populates="source")


class ImportRun(Base):
    """One execution of an importer; every stat row points back to the run that wrote it."""

    __tablename__ = "import_run"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("data_source.id"))
    kind: Mapped[str] = mapped_column(String(50))  # e.g. "tm_players", "af_team_players"
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), default="running")  # running/success/partial/failed
    requests_used: Mapped[int] = mapped_column(Integer, default=0)
    rows_written: Mapped[int] = mapped_column(Integer, default=0)
    notes: Mapped[str | None] = mapped_column(Text)

    source: Mapped[DataSource] = relationship(back_populates="import_runs")
