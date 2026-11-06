"""Turn a request into filters: the language model when configured, otherwise (or on any failure) rules."""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.assistant import llm, rules
from app.assistant.filters import AssistantFilters
from app.core.config import get_settings
from app.models import League
from app.optimization.diagnose import ROLE_NAMES


@dataclass
class Interpretation:
    engine: str                     # "ai" or "rules"
    filters: AssistantFilters
    understood: list[str]           # what will be applied, in plain words
    not_applied: list[str]          # understood but not usable here (e.g. a league not in the app yet)
    note: str | None                # e.g. why the AI was not used


def _eur(n: int) -> str:
    return f"€{n / 1_000_000:g}m" if n >= 1_000_000 else f"€{n / 1_000:g}k"


def describe(f: AssistantFilters, league_names: dict[str, str]) -> list[str]:
    out = []
    def one(r):
        name = ROLE_NAMES[r].rstrip("s")
        return name[0].upper() + name[1:]
    if f.role_counts:
        out += [f"{n} × {one(r).lower()}" for r, n in f.role_counts.items()]
    else:
        out += [one(r) for r in f.roles]
    if f.age_min is not None and f.age_max is not None:
        out.append(f"Age {f.age_min}–{f.age_max}")
    elif f.age_max is not None:
        out.append(f"Age {f.age_max} or younger")
    elif f.age_min is not None:
        out.append(f"Age {f.age_min} or older")
    if f.max_price_eur:
        out.append(f"Up to {_eur(f.max_price_eur)} per player")
    if f.budget_eur:
        out.append(f"Budget {_eur(f.budget_eur)}")
    out += [league_names.get(c, c) for c in f.leagues]
    out += [f"Nationality: {n}" for n in f.nationalities]
    if f.still_playing:
        out.append("Still playing in 2025/26")
    if f.include_low_minutes:
        out.append("Includes 450–899 minutes")
    if f.formation:
        out.append(f"Formation {f.formation}")
    return out


def interpret(db: Session, text: str, page: str = "players") -> Interpretation:
    settings = get_settings()
    bare = "price" if page == "players" else "budget"
    note = None
    filters = None
    engine = "rules"
    if settings.anthropic_api_key:
        try:
            filters = llm.parse(text, settings.anthropic_api_key, settings.assistant_model, bare)
            engine = "ai"
        except llm.LLMUnavailable as e:
            note = f"Used the built-in rules because {e}."
    if filters is None:
        filters, _ = rules.parse(text, bare)

    leagues = {lg.tm_competition_id: lg for lg in db.scalars(select(League).where(League.tm_competition_id.is_not(None)))}
    names = {code: lg.name for code, lg in leagues.items()}
    usable = [c for c in filters.leagues if c in leagues and leagues[c].enabled]
    missing = [c for c in filters.leagues if c not in usable]
    not_applied = [f"{names.get(c, c)} (not in the app's data yet)" for c in missing]
    filters = filters.model_copy(update={"leagues": usable})
    return Interpretation(engine, filters, describe(filters, names), not_applied, note)


def league_ids(db: Session, codes: list[str]) -> list[int]:
    return list(db.scalars(select(League.id).where(League.tm_competition_id.in_(codes)))) if codes else []
