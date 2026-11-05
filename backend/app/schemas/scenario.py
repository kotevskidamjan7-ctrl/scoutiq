"""Saved scenario schemas."""

from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.optimize import OptimizeRequest, OptimizeResponse


class ScenarioCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=120, examples=["4-3-3 under EUR 15m"])
    request: OptimizeRequest


class ScenarioSummary(BaseModel):
    id: int
    name: str
    mode: str
    status: str
    total_score: float | None
    cost_eur: int | None
    budget_eur: int
    created_at: datetime


class ScenarioOut(ScenarioSummary):
    request: OptimizeRequest
    result: OptimizeResponse
