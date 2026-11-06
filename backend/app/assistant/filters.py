"""What the assistant may produce: filters, nothing else (FR-15).

Both parsers (rules and the optional language model) must return this structure. It is validated
like any user input, so a parser can never ask the optimizer for something the form could not.
"""

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.optimization.model import FORMATIONS

Role = Literal["GK", "CB", "FB", "CM", "AW", "ST"]

# Transfermarkt competition codes of every league the app knows (enabled or not)
LEAGUE_CODES = ("GB1", "ES1", "IT1", "L1", "FR1", "PO1", "NL1", "BE1", "TR1", "A1", "C1", "PL1", "KR1", "SER1")


class AssistantFilters(BaseModel):
    roles: list[Role] = Field([], description="Positions asked for, in the order mentioned")
    role_counts: dict[Role, int] = Field({}, description="How many of each position, only when a number was given")
    age_min: int | None = Field(None, ge=15, le=45)
    age_max: int | None = Field(None, ge=15, le=45)
    max_price_eur: int | None = Field(None, gt=0, le=500_000_000, description="Highest market value for one player")
    budget_eur: int | None = Field(None, gt=0, le=2_000_000_000, description="Total transfer budget")
    leagues: list[str] = Field([], description="Transfermarkt competition codes of the leagues to search")
    nationalities: list[str] = Field([], description="Transfermarkt country names, e.g. 'North Macedonia'")
    still_playing: bool | None = Field(None, description="900+ league minutes in 2025/26")
    include_low_minutes: bool | None = Field(None, description="Also players with 450-899 minutes in 2024/25")
    formation: str | None = None

    @model_validator(mode="after")
    def check(self):
        if self.age_min is not None and self.age_max is not None and self.age_min > self.age_max:
            raise ValueError("age_min is greater than age_max")
        if self.formation is not None and self.formation not in FORMATIONS:
            raise ValueError(f"formation must be one of {sorted(FORMATIONS)}")
        bad = [code for code in self.leagues if code not in LEAGUE_CODES]
        if bad:
            raise ValueError(f"unknown league codes: {bad}")
        if any(n < 1 or n > 11 for n in self.role_counts.values()):
            raise ValueError("role counts must be 1 to 11")
        for r in self.role_counts:
            if r not in self.roles:
                self.roles.append(r)
        return self

    def is_empty(self) -> bool:
        return self == AssistantFilters()
