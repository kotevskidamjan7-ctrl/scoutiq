"""Request and response models for POST /api/v1/optimize/squad (Mode A)."""

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.optimization.model import FORMATIONS, ROLES

Role = Literal["GK", "CB", "FB", "CM", "AW", "ST"]


class OptimizeRequest(BaseModel):
    model_config = {"json_schema_extra": {"examples": [{"budget_eur": 15000000, "formation": "4-3-3"},
                                                       {"budget_eur": 2000000, "needs": {"CM": 2, "ST": 1}}]}}

    budget_eur: int = Field(..., gt=0, le=2_000_000_000, description="Transfer budget in EUR")
    formation: str | None = Field(None, description=f"One of {sorted(FORMATIONS)}")
    squad_size: int | None = Field(None, ge=12, le=30, description="Complete squad instead of a starting XI")
    needs: dict[Role, int] | None = Field(None, description='Exact signings per role, e.g. {"ST": 1, "CM": 1}')
    age_min: int | None = Field(None, ge=15, le=45)
    age_max: int | None = Field(None, ge=15, le=45)
    league_ids: list[int] = []
    nationalities: list[str] = []
    exclude_nationalities: list[str] = []
    max_price_eur: int | None = Field(None, gt=0)
    min_minutes: int = Field(900, ge=450, le=4000, description="League minutes in 2024/25")
    min_minutes_next: int = Field(900, ge=0, le=4000, description="League minutes in 2025/26; 0 switches the filter off")
    max_per_club: int | None = Field(None, ge=1, le=11)
    alternatives: int = Field(2, ge=0, le=3)
    score: Literal["within", "adjusted"] = "within"

    @model_validator(mode="after")
    def check(self):
        if self.formation is not None and self.formation not in FORMATIONS:
            raise ValueError(f"formation must be one of {sorted(FORMATIONS)}")
        if (self.formation is None) == (self.needs is None):
            raise ValueError("give either a formation or needs, not both")
        if self.squad_size is not None and self.formation is None:
            raise ValueError("squad_size requires a formation")
        if self.needs is not None:
            if any(n < 0 or n > 11 for n in self.needs.values()) or sum(self.needs.values()) == 0:
                raise ValueError("needs must ask for 1 to 11 players per role, at least one in total")
        if self.age_min is not None and self.age_max is not None and self.age_min > self.age_max:
            raise ValueError("age_min is greater than age_max")
        return self


class PlayerOut(BaseModel):
    slot: str
    player_id: int
    name: str
    role: str
    score: float
    price_eur: int
    valuation_date: str | None
    age: int | None
    club_2024_25: str
    league: str
    minutes_2024_25: int
    minutes_2025_26: int
    reliability: str
    position_consistent: bool | None


class TeamOut(BaseModel):
    total_score: float
    cost_eur: int
    players: list[PlayerOut]


class Suggestion(BaseModel):
    change: str
    total_score: float
    cost_eur: int
    unlock_ids: list[int] = []  # Mode B: players to unlock for this change
    add_roles: list[str] = []   # Mode B: positions to add to the positions to sign


class Diagnosis(BaseModel):
    reason: str
    cheapest_cost_eur: int | None
    budget_shortfall_eur: int | None
    suggestions: list[Suggestion]


class OptimizeResponse(BaseModel):
    status: Literal["optimal", "feasible", "infeasible", "unknown", "error"]
    budget_eur: int
    remaining_budget_eur: int | None
    solve_time_ms: float
    eligible_players: int
    team: TeamOut | None
    alternatives: list[TeamOut]
    diagnosis: Diagnosis | None
    notes: list[str]


class ImproveRequest(BaseModel):
    """Mode B: improve an existing squad with at most `max_signings` purchases."""
    model_config = {"json_schema_extra": {"examples": [
        {"formation": "4-3-3", "budget_eur": 5000000, "owned_player_ids": [101, 102, 103], "max_signings": 2}]}}

    formation: str = Field(..., description=f"One of {sorted(FORMATIONS)}")
    budget_eur: int = Field(..., ge=0, le=2_000_000_000, description="Transfer budget in EUR; 0 shows the current best XI")
    owned_player_ids: list[int] = Field(..., min_length=1, max_length=60, description="The club's current players")
    locked_player_ids: list[int] = Field([], max_length=11, description="Own players who must start")
    left_player_ids: list[int] = Field([], max_length=80, description="Players who left the club: never suggested as signings")
    max_signings: int = Field(3, ge=0, le=11)
    signing_roles: list[Role] = Field([], description="Buy only for these positions; empty = any position")
    age_min: int | None = Field(None, ge=15, le=45)
    age_max: int | None = Field(None, ge=15, le=45)
    league_ids: list[int] = []
    max_price_eur: int | None = Field(None, gt=0)
    min_minutes: int = Field(900, ge=450, le=4000)
    min_minutes_next: int = Field(900, ge=0, le=4000)
    alternatives: int = Field(2, ge=0, le=3)
    score: Literal["within", "adjusted"] = "within"

    @model_validator(mode="after")
    def check(self):
        if self.formation not in FORMATIONS:
            raise ValueError(f"formation must be one of {sorted(FORMATIONS)}")
        if not set(self.locked_player_ids) <= set(self.owned_player_ids):
            raise ValueError("locked players must be part of the squad")
        if set(self.left_player_ids) & set(self.owned_player_ids):
            raise ValueError("a player cannot be both in the squad and gone from it")
        if self.age_min is not None and self.age_max is not None and self.age_min > self.age_max:
            raise ValueError("age_min is greater than age_max")
        return self


class ImprovePlayerOut(PlayerOut):
    signing: bool


class ImproveTeamOut(BaseModel):
    total_score: float
    cost_eur: int
    players: list[ImprovePlayerOut]


class SquadNote(BaseModel):
    player_id: int
    name: str


class ImproveResponse(BaseModel):
    status: Literal["optimal", "feasible", "infeasible", "unknown", "error"]
    budget_eur: int
    remaining_budget_eur: int | None
    solve_time_ms: float
    eligible_players: int
    current: ImproveTeamOut | None                 # best XI from the current squad alone
    current_missing: dict[str, int]                # role -> players the current squad lacks for the formation
    team: ImproveTeamOut | None                    # best XI with signings
    gain: float | None                             # team total - current total (both complete XIs)
    alternatives: list[ImproveTeamOut]
    diagnosis: Diagnosis | None
    unscored: list[SquadNote]                      # squad players without a 2024/25 score (left out)
    notes: list[str]


class ClubOut(BaseModel):
    id: int
    name: str
    league: str


class SquadPlayerOut(BaseModel):
    player_id: int
    name: str
    age: int | None
    position: str | None
    role: str | None
    score: float | None
    reliability: str | None
    price_eur: int | None
    minutes_2025_26: int


class SquadOut(BaseModel):
    club: ClubOut
    players: list[SquadPlayerOut]
