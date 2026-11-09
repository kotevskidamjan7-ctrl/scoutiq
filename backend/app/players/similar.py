"""Similar players: the nearest statistical profiles in the same role.

A player's profile is his vector of per-metric percentiles (0-100) from the scoring model, for the
role he was scored in. Distance between two players is the weighted root-mean-square difference
over the metrics both have, using the role's model weights, so the metrics that matter most for
the role count most. Similarity = 100 - that distance (percentile points), floored at 0.

Percentiles are within each league: a similar profile in a weaker league means "plays the same way
relative to his league", not "is as good". The league-adjusted score is shown next to it for that.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ScoutingScore
from app.players.service import SCORED_SEASON, Row, _model, all_rows
from app.scoring import model_v1 as M

MIN_SHARED_WEIGHT = 0.6   # the metrics both players have must carry at least this share of the role's weight
NOTABLE_DIFF = 15.0       # percentile points: a difference worth naming ("stronger in", "weaker in")


@dataclass
class Profile:
    player_id: int
    role: str
    league_id: int
    minutes: int
    percentiles: dict[str, float]


def profiles(db: Session) -> dict[int, Profile]:
    """Each scored player's profile, from the league where he played most in the scored season."""
    model = _model(db)
    if model is None:
        return {}
    out: dict[int, Profile] = {}
    for sc in db.scalars(select(ScoutingScore).where(ScoutingScore.model_id == model.id,
                                                     ScoutingScore.season == SCORED_SEASON)):
        b = sc.breakdown or {}
        pct = {k: float(m["percentile"]) for k, m in (b.get("metrics") or {}).items() if m.get("percentile") is not None}
        if not pct:
            continue
        prof = Profile(sc.player_id, sc.role, sc.league_id, int(b.get("minutes") or 0), pct)
        if sc.player_id not in out or prof.minutes > out[sc.player_id].minutes:
            out[sc.player_id] = prof
    return out


def distance(a: dict[str, float], b: dict[str, float], weights: dict[str, float]) -> float | None:
    """Weighted RMS difference in percentile points over shared metrics; None if they share too little."""
    shared = [k for k in weights if k in a and k in b]
    total = sum(weights.values())
    w = sum(weights[k] for k in shared)
    if not shared or total <= 0 or w / total < MIN_SHARED_WEIGHT:
        return None
    return math.sqrt(sum(weights[k] * (a[k] - b[k]) ** 2 for k in shared) / w)


def differences(target: dict[str, float], other: dict[str, float], weights: dict[str, float]) -> tuple[list, list]:
    """The other player's notable strengths and weaknesses compared with the target, most important first."""
    diffs = [(k, other[k] - target[k]) for k in weights if k in target and k in other]
    def label(k, better: bool):
        m = M.METRICS.get(k)
        if m is None:
            return k
        # percentiles of lower-is-better metrics are flipped (higher = better), so say which way it goes
        if not m.lower_is_better:
            return m.label
        base = re.sub(r"\s*\([^)]*\)$", "", m.label)  # "Card points per 90 (yellow 1, red 3)" -> "Card points per 90"
        return f"{base} ({'fewer' if better else 'more'})"
    stronger = sorted((d for d in diffs if d[1] >= NOTABLE_DIFF), key=lambda d: -d[1] * weights[d[0]])
    weaker = sorted((d for d in diffs if d[1] <= -NOTABLE_DIFF), key=lambda d: d[1] * weights[d[0]])
    return ([{"metric": label(k, True), "diff": round(d, 1)} for k, d in stronger[:2]],
            [{"metric": label(k, False), "diff": round(d, 1)} for k, d in weaker[:2]])


def similar(db: Session, player_id: int, *, limit: int = 10, max_price_eur: int | None = None,
            max_age: int | None = None, league_ids: list[int] | None = None,
            exclude_ids: list[int] | None = None, score: str = "within", include_low: bool = False) -> dict | None:
    """The `limit` most similar players to `player_id` in his role, after the filters.

    Returns None if the player has no scored profile.
    """
    profs = profiles(db)
    target = profs.get(player_id)
    if target is None:
        return None
    weights = M.WEIGHTS.get(target.role, {})
    rows: dict[int, Row] = {r.player_id: r for r in all_rows(db)}
    me = rows.get(player_id)
    excluded = set(exclude_ids or []) | {player_id}
    leagues = set(league_ids or [])

    found = []
    for pid, prof in profs.items():
        if pid in excluded or prof.role != target.role:
            continue
        r = rows.get(pid)
        if r is None:
            continue
        if not include_low and r.reliability == "low":
            continue
        if max_price_eur is not None and (r.price_eur is None or r.price_eur > max_price_eur):
            continue
        if max_age is not None and (r.age is None or r.age > max_age):
            continue
        if leagues and r.league_id not in leagues:
            continue
        if score == "adjusted" and r.score_adjusted is None:
            continue
        d = distance(target.percentiles, prof.percentiles, weights)
        if d is None:
            continue
        found.append((d, r, prof))
    found.sort(key=lambda t: (t[0], t[1].player_id))

    results = []
    for d, r, prof in found[:limit]:
        stronger, weaker = differences(target.percentiles, prof.percentiles, weights)
        results.append({
            "player_id": r.player_id, "name": r.name, "age": r.age, "nationality": r.nationality,
            "role": r.role, "league_id": r.league_id, "league": r.league, "club": r.club,
            "score": r.score_adjusted if score == "adjusted" else r.score,
            "score_adjusted": r.score_adjusted, "value_for_money": r.value_for_money,
            "reliability": r.reliability, "minutes": r.minutes, "minutes_next": r.minutes_next,
            "price_eur": r.price_eur, "similarity": round(max(0.0, 100 - d), 1),
            "stronger_in": stronger, "weaker_in": weaker,
        })
    shared = sorted((k for k in weights if k in target.percentiles), key=lambda k: -weights[k])
    return {
        "player": {
            "player_id": player_id, "name": me.name if me else "", "role": target.role,
            "league": me.league if me else "", "score": (me.score_adjusted if score == "adjusted" else me.score) if me else None,
            "price_eur": me.price_eur if me else None,
        },
        "metrics": [M.METRICS[k].label if k in M.METRICS else k for k in shared],
        "candidates": len(found),
        "results": results,
    }
