"""Import every model so SQLAlchemy and Alembic see all tables."""

from app.models.league import Club, ClubSourceId, League, LeagueStrength
from app.models.player import LinkCandidate, MarketValuation, Player, PlayerSeasonStats, PlayerSourceId
from app.models.scoring import LeagueAdjustment, ScoringModel, ScoutingScore, StatFieldCoverage
from app.models.source import DataSource, ImportRun
from app.models.user import AppUser, Scenario, ScenarioPlayer

__all__ = [
    "AppUser",
    "Club",
    "ClubSourceId",
    "DataSource",
    "ImportRun",
    "League",
    "LeagueAdjustment",
    "LeagueStrength",
    "LinkCandidate",
    "MarketValuation",
    "Player",
    "PlayerSeasonStats",
    "PlayerSourceId",
    "Scenario",
    "ScenarioPlayer",
    "ScoringModel",
    "ScoutingScore",
    "StatFieldCoverage",
]
