"""Request, candidate and solution types for the squad optimizer (Phase 5 model document)."""

from dataclasses import dataclass, field, replace
from datetime import date

ROLES = ("GK", "CB", "FB", "CM", "AW", "ST")

# Formation -> players per role in a starting XI (model document, "Formations as role counts")
FORMATIONS: dict[str, dict[str, int]] = {
    "4-3-3": {"GK": 1, "CB": 2, "FB": 2, "CM": 3, "AW": 2, "ST": 1},
    "4-2-3-1": {"GK": 1, "CB": 2, "FB": 2, "CM": 2, "AW": 3, "ST": 1},
    "4-4-2": {"GK": 1, "CB": 2, "FB": 2, "CM": 2, "AW": 2, "ST": 2},
    "3-5-2": {"GK": 1, "CB": 3, "FB": 2, "CM": 3, "AW": 0, "ST": 2},
    "3-4-3": {"GK": 1, "CB": 3, "FB": 2, "CM": 2, "AW": 2, "ST": 1},
}

# Pitch slots per formation, for display only (does not affect the optimum)
SLOTS: dict[str, list[tuple[str, str]]] = {
    "4-3-3": [("GK", "GK"), ("LB", "FB"), ("LCB", "CB"), ("RCB", "CB"), ("RB", "FB"),
              ("LCM", "CM"), ("CM", "CM"), ("RCM", "CM"), ("LW", "AW"), ("ST", "ST"), ("RW", "AW")],
    "4-2-3-1": [("GK", "GK"), ("LB", "FB"), ("LCB", "CB"), ("RCB", "CB"), ("RB", "FB"),
                ("LDM", "CM"), ("RDM", "CM"), ("LAM", "AW"), ("CAM", "AW"), ("RAM", "AW"), ("ST", "ST")],
    "4-4-2": [("GK", "GK"), ("LB", "FB"), ("LCB", "CB"), ("RCB", "CB"), ("RB", "FB"),
              ("LM", "AW"), ("LCM", "CM"), ("RCM", "CM"), ("RM", "AW"), ("LST", "ST"), ("RST", "ST")],
    "3-5-2": [("GK", "GK"), ("LCB", "CB"), ("CB", "CB"), ("RCB", "CB"), ("LWB", "FB"),
              ("LCM", "CM"), ("CM", "CM"), ("RCM", "CM"), ("RWB", "FB"), ("LST", "ST"), ("RST", "ST")],
    "3-4-3": [("GK", "GK"), ("LCB", "CB"), ("CB", "CB"), ("RCB", "CB"), ("LWB", "FB"),
              ("LCM", "CM"), ("RCM", "CM"), ("RWB", "FB"), ("LW", "AW"), ("ST", "ST"), ("RW", "AW")],
}


@dataclass(frozen=True)
class Candidate:
    player_id: int
    name: str
    role: str
    score: float                  # 0-100 (within-league, or adjusted if requested and available)
    price: int                    # EUR, latest Transfermarkt market value
    league_id: int
    league: str
    club_id: int | None = None
    club: str = ""
    nationality: str | None = None
    birth_date: date | None = None
    foot: str | None = None
    minutes: int = 0              # league minutes in the scored season
    minutes_next: int = 0         # league minutes in the following season (supported leagues)
    valuation_date: date | None = None
    reliability: str = ""
    position_consistent: bool | None = None


@dataclass(frozen=True)
class Request:
    budget: int
    role_min: dict[str, int]
    role_max: dict[str, int]
    squad_size: int
    formation: str | None = None
    mode: str = "build"                     # "build" (Mode A) or "improve" (Mode B)
    kept_ids: tuple[int, ...] = ()          # Mode B: players kept from the current squad (price 0)
    exclude_ids: tuple[int, ...] = ()       # Mode B: the club's own players are not bought again
    age_min: int | None = None
    age_max: int | None = None
    league_ids: tuple[int, ...] = ()        # empty = all
    nationalities: tuple[str, ...] = ()     # empty = all
    exclude_nationalities: tuple[str, ...] = ()
    max_price: int | None = None
    min_minutes: int = 900
    min_minutes_next: int | None = None
    max_per_club: int | None = None
    reference_date: date = field(default_factory=date.today)
    alternatives: int = 2
    time_limit_s: float = 10.0

    def relaxed(self, **changes) -> "Request":
        return replace(self, **changes)


def formation_request(formation: str, budget: int, **kw) -> Request:
    """Starting XI for a formation: L_r = U_r = the formation's count, N = 11."""
    counts = FORMATIONS[formation]
    return Request(budget=budget, role_min=dict(counts), role_max=dict(counts), squad_size=11,
                   formation=formation, **kw)


def squad_request(formation: str, budget: int, size: int = 22, **kw) -> Request:
    """Complete squad: each role between its formation count and twice that, at least 2 goalkeepers."""
    counts = FORMATIONS[formation]
    role_min = {r: max(c, 2 if r == "GK" else c) for r, c in counts.items()}
    role_max = {r: max(2 * c, role_min[r]) for r, c in counts.items()}
    if sum(role_min.values()) > size or sum(role_max.values()) < size:
        raise ValueError(f"squad size {size} is not possible for {formation}")
    return Request(budget=budget, role_min=role_min, role_max=role_max, squad_size=size, formation=formation, **kw)


def positions_request(needs: dict[str, int], budget: int, **kw) -> Request:
    """Exactly these signings, e.g. {"ST": 1, "CM": 1, "CB": 1} (the brief's EUR 500k example)."""
    counts = {r: int(needs.get(r, 0)) for r in ROLES}
    return Request(budget=budget, role_min=dict(counts), role_max=dict(counts), squad_size=sum(counts.values()), **kw)


def age_on(birth: date | None, ref: date) -> int | None:
    if birth is None:
        return None
    return ref.year - birth.year - ((ref.month, ref.day) < (birth.month, birth.day))


def apply_filters(candidates: list[Candidate], req: Request) -> list[Candidate]:
    """Candidates that may be BOUGHT under the request (kept players are handled separately)."""
    leagues, nats, excl = set(req.league_ids), set(req.nationalities), set(req.exclude_nationalities)
    skip = set(req.exclude_ids) | set(req.kept_ids)
    out = []
    for c in candidates:
        if c.player_id in skip or c.price is None or c.price <= 0:
            continue
        if c.minutes < req.min_minutes:
            continue
        if req.min_minutes_next is not None and c.minutes_next < req.min_minutes_next:
            continue
        if leagues and c.league_id not in leagues:
            continue
        if nats and c.nationality not in nats:
            continue
        if excl and c.nationality in excl:
            continue
        if req.max_price is not None and c.price > req.max_price:
            continue
        if req.age_min is not None or req.age_max is not None:
            age = age_on(c.birth_date, req.reference_date)
            if age is None:
                continue
            if req.age_min is not None and age < req.age_min:
                continue
            if req.age_max is not None and age > req.age_max:
                continue
        out.append(c)
    return out


@dataclass
class Team:
    players: list[Candidate]
    kept_ids: frozenset[int] = frozenset()

    @property
    def signings(self) -> list[Candidate]:
        return [p for p in self.players if p.player_id not in self.kept_ids]

    @property
    def total_score(self) -> float:
        return round(sum(p.score for p in self.players), 1)

    @property
    def cost(self) -> int:
        return sum(p.price for p in self.signings)

    def ids(self) -> set[int]:
        return {p.player_id for p in self.players}


@dataclass
class Solution:
    status: str                          # optimal / feasible (time limit) / infeasible / error
    team: Team | None = None
    budget: int = 0
    solve_time_ms: float = 0.0
    alternatives: list[Team] = field(default_factory=list)
    diagnosis: dict | None = None
    violations: list[str] = field(default_factory=list)
    candidates_considered: int = 0

    @property
    def remaining_budget(self) -> int | None:
        return None if self.team is None else self.budget - self.team.cost
