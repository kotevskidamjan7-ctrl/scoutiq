"""Saved scenario schemas: squad builder (mode "build") and club improvement (mode "improve")."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from app.schemas.optimize import ImproveRequest, ImproveResponse, OptimizeRequest, OptimizeResponse


class ScenarioCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=120, examples=["4-3-3 under EUR 15m"])
    request: OptimizeRequest


class ImproveScenarioCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=120, examples=["Brentford: two signings, EUR 10m"])
    club_id: int | None = Field(None, description="The club whose squad was improved, if one was picked")
    request: ImproveRequest


class ScenarioSummary(BaseModel):
    id: int
    name: str
    mode: str
    status: str
    total_score: float | None
    cost_eur: int | None
    budget_eur: int
    created_at: datetime
    club_name: str | None = None   # improve only
    gain: float | None = None      # improve only: XI score with signings minus the XI now
    signings: int | None = None    # improve only


class ScenarioOut(ScenarioSummary):
    mode: Literal["build"]
    request: OptimizeRequest
    result: OptimizeResponse


class ImproveScenarioOut(ScenarioSummary):
    mode: Literal["improve"]
    club_id: int | None
    request: ImproveRequest
    result: ImproveResponse


AnyScenarioOut = Annotated[ScenarioOut | ImproveScenarioOut, Field(discriminator="mode")]
