"""Assistant (FR-15): turns a typed request into filters for the page. It never selects players."""

from fastapi import APIRouter, Depends
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.assistant import service
from app.assistant.filters import AssistantFilters
from app.db.session import get_db

router = APIRouter(tags=["assistant"], dependencies=[Depends(get_current_user)])


class InterpretRequest(BaseModel):
    model_config = {"json_schema_extra": {"examples": [{"text": "a young left-back under €2m who still plays"}]}}
    text: str = Field(..., min_length=2, max_length=400)
    page: Literal["players", "builder", "improve"] = Field(
        "players", description="Where the filters go: on 'players' an amount alone is a price, elsewhere a budget")


class InterpretResponse(BaseModel):
    engine: str
    filters: AssistantFilters
    league_ids: list[int]
    understood: list[str]
    not_applied: list[str]
    note: str | None


@router.post("/assistant/interpret", response_model=InterpretResponse)
def interpret(body: InterpretRequest, db: Session = Depends(get_db)) -> InterpretResponse:
    """Read a request in English or Macedonian and return filters. The page shows them before applying."""
    r = service.interpret(db, body.text, body.page)
    return InterpretResponse(engine=r.engine, filters=r.filters, league_ids=service.league_ids(db, r.filters.leagues),
                             understood=r.understood, not_applied=r.not_applied, note=r.note)
