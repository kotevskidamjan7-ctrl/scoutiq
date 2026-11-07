"""League-strength adjustment (methodology section "League-strength adjustment").

1. League strength E per league and season: mean ClubElo of its clubs (method 'mean_club_elo'), or,
   when ClubElo is unavailable, UEFA association season points (method 'uefa_season_points').
   E differences are measured in UNITS: 100 Elo points, or 10 UEFA points.
2. Calibration on Transfermarkt data, seasons S and S+1, roles ST and AW:
       z = probit( percentile of (goals + assists) per 90 within role, league, season ; >= 900 min )
       z(S+1) - z(S) = alpha + beta * (E_to - E_from) / 100 + error
   Movers changed league, stayers did not (control group). 95% CI for beta by bootstrap.
3. Decision rule: use the adjustment only if beta < 0, its CI excludes 0, and there are
   at least MIN_MOVERS movers. Otherwise adjusted scores stay empty and the report says why.
4. Apply:  S_adj = 100 * Phi( Phi^-1(S / 100) - beta * (E_L - E_ref) / 100 )

Usage (inside the backend container, after ingestion.clubelo and app.scoring.run):
    python -m app.scoring.league_adjust --season 2024 --strength uefa      (or --strength clubelo)
"""

import argparse
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from statistics import NormalDist

import numpy as np
import pandas as pd
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models import DataSource, League, LeagueAdjustment, LeagueStrength, Player, PlayerSeasonStats, ScoringModel, ScoutingScore
from app.scoring import model_v1 as M
from app.scoring.engine import midrank_percentile

CALIBRATION_ROLES = ("ST", "AW")
# strength sources: database method name, and how many of its points make one unit of delta_e
STRENGTH = {
    "clubelo": {"method": "mean_club_elo", "unit": 100.0, "label": "100 ClubElo points"},
    "uefa": {"method": "uefa_season_points", "unit": 10.0, "label": "10 UEFA season points"},
}
MIN_MOVERS = 15
BOOTSTRAP = 1000
_N = NormalDist()


def probit(p: np.ndarray) -> np.ndarray:
    return np.array([_N.inv_cdf(x) for x in np.clip(p, 0.01, 0.99)])


def season_strength(session: Session, seasons: list[int], method: str | None = None) -> dict[tuple[int, int], float]:
    """(league_id, season) -> strength over the season's dates, from one method (None = any non-UEFA method,
    i.e. ClubElo as before)."""
    out = {}
    for season in seasons:
        which = (LeagueStrength.method == method) if method else (LeagueStrength.method != STRENGTH["uefa"]["method"])
        rows = session.execute(
            select(LeagueStrength.league_id, func.avg(LeagueStrength.mean_club_elo))
            .where(LeagueStrength.as_of_date >= date(season, 8, 1), LeagueStrength.as_of_date <= date(season + 1, 6, 30),
                   which)
            .group_by(LeagueStrength.league_id)
        ).all()
        out.update({(lid, season): float(e) for lid, e in rows})
    return out


# ---------- calibration (pure) ----------

@dataclass
class Calibration:
    season: int
    beta: float | None = None
    alpha: float | None = None
    ci_low: float | None = None
    ci_high: float | None = None
    n_movers: int = 0
    n_stayers: int = 0
    accepted: bool = False
    reason: str = ""
    e_ref: float | None = None
    league_strength: dict = field(default_factory=dict)


def standing(tm: pd.DataFrame) -> pd.DataFrame:
    """tm: player_id, league_id, season, role, minutes, goals, assists (one row per player-league-season).
    Returns the main league per player-season (most minutes) with the probit standing z."""
    tm = tm[tm["role"].isin(CALIBRATION_ROLES)].copy()
    tm = tm.sort_values("minutes", ascending=False).drop_duplicates(["player_id", "season"])
    tm = tm[tm["minutes"] >= M.REFERENCE_MINUTES].copy()
    tm["ga90"] = (tm["goals"].fillna(0) + tm["assists"].fillna(0)) / tm["minutes"] * 90
    tm["z"] = np.nan
    for _, g in tm.groupby(["league_id", "season", "role"]):
        if len(g) >= M.MIN_REFERENCE_PLAYERS:
            tm.loc[g.index, "z"] = probit(midrank_percentile(g["ga90"].to_numpy(), g["ga90"].to_numpy()))
    return tm.dropna(subset=["z"])


def fit(pairs: pd.DataFrame, unit: float = 100.0) -> tuple[float, float]:
    X = np.column_stack([np.ones(len(pairs)), pairs["delta_e"] / unit])
    coef, *_ = np.linalg.lstsq(X, pairs["delta_z"].to_numpy(), rcond=None)
    return float(coef[0]), float(coef[1])


def calibrate(tm: pd.DataFrame, strength: dict, season: int, enabled_league_ids: list[int],
              seed: int = 2024, unit: float = 100.0) -> Calibration:
    cal = Calibration(season=season)
    s = standing(tm)
    a = s[s["season"] == season][["player_id", "league_id", "z"]]
    b = s[s["season"] == season + 1][["player_id", "league_id", "z"]]
    pairs = a.merge(b, on="player_id", suffixes=("_from", "_to"))
    # league strength averaged over both seasons, so a league's own drift is not counted as a move
    e = {lid: np.mean([v for (l2, _), v in strength.items() if l2 == lid])
         for lid in set(pairs["league_id_from"]) | set(pairs["league_id_to"])
         if any(l2 == lid for (l2, _) in strength)}
    pairs = pairs[pairs["league_id_from"].isin(e) & pairs["league_id_to"].isin(e)].copy()
    pairs["delta_z"] = pairs["z_to"] - pairs["z_from"]
    pairs["delta_e"] = pairs["league_id_to"].map(e) - pairs["league_id_from"].map(e)
    movers = pairs["league_id_from"] != pairs["league_id_to"]
    cal.n_movers, cal.n_stayers = int(movers.sum()), int((~movers).sum())
    cal.league_strength = {int(k): round(float(v), 2) for k, v in e.items()}
    ref = [strength[(lid, season)] for lid in enabled_league_ids if (lid, season) in strength]
    cal.e_ref = float(np.mean(ref)) if ref else None

    if cal.n_movers < MIN_MOVERS:
        cal.reason = f"only {cal.n_movers} league movers with >= 900 minutes in both seasons (minimum {MIN_MOVERS})"
        return cal
    cal.alpha, cal.beta = fit(pairs, unit)
    rng = np.random.default_rng(seed)
    betas = [fit(pairs.iloc[rng.integers(0, len(pairs), len(pairs))], unit)[1] for _ in range(BOOTSTRAP)]
    cal.ci_low, cal.ci_high = float(np.percentile(betas, 2.5)), float(np.percentile(betas, 97.5))
    if cal.ci_high < 0:
        cal.accepted = True
        cal.reason = "beta negative and its 95% interval excludes zero"
    elif cal.ci_low > 0:
        cal.reason = "beta positive: moving to a stronger league did not lower standing, contrary to the model"
    else:
        cal.reason = "95% interval for beta includes zero: no reliable league effect in the data"
    return cal


def adjusted_score(score: float, e_league: float, e_ref: float, beta: float, unit: float = 100.0) -> float:
    z = _N.inv_cdf(min(max(score, 0.5), 99.5) / 100)
    return round(100 * _N.cdf(z - beta * (e_league - e_ref) / unit), 1)


# ---------- database ----------

def load_tm(session: Session, seasons: list[int]) -> pd.DataFrame:
    tm = session.scalar(select(DataSource).where(DataSource.code == "transfermarkt"))
    rows = session.execute(
        select(PlayerSeasonStats.player_id, PlayerSeasonStats.league_id, PlayerSeasonStats.season,
               func.sum(PlayerSeasonStats.minutes), func.sum(PlayerSeasonStats.goals), func.sum(PlayerSeasonStats.assists),
               Player.primary_position)
        .join(Player, Player.id == PlayerSeasonStats.player_id)
        .where(PlayerSeasonStats.source_id == tm.id, PlayerSeasonStats.season.in_(seasons))
        .group_by(PlayerSeasonStats.player_id, PlayerSeasonStats.league_id, PlayerSeasonStats.season,
                  Player.primary_position)
    ).all()
    df = pd.DataFrame(rows, columns=["player_id", "league_id", "season", "minutes", "goals", "assists", "position"])
    df["role"] = df["position"].map(M.ROLE_BY_SUBPOSITION)
    return df


def apply(session: Session, model: ScoringModel, season: int) -> int:
    """Write score_adjusted from the stored calibration (NULL if not accepted). Returns rows adjusted."""
    session.execute(update(ScoutingScore).where(ScoutingScore.model_id == model.id, ScoutingScore.season == season)
                    .values(score_adjusted=None))
    cal = session.scalar(select(LeagueAdjustment).where(LeagueAdjustment.model_id == model.id,
                                                        LeagueAdjustment.season == season))
    if cal is None or not cal.accepted:
        return 0
    src = STRENGTH[(cal.details or {}).get("strength", "clubelo")]
    unit = src["unit"]
    strength = season_strength(session, [season], src["method"] if src is STRENGTH["uefa"] else None)
    count = 0
    for sc in session.scalars(select(ScoutingScore).where(ScoutingScore.model_id == model.id, ScoutingScore.season == season)):
        e = strength.get((sc.league_id, season))
        if e is not None:
            sc.score_adjusted = adjusted_score(sc.score_within_league, e, cal.e_ref, cal.beta, unit)
            count += 1
    session.flush()
    return count


def run(session: Session, season: int, source: str = "clubelo") -> tuple[Calibration, int]:
    model = session.scalar(select(ScoringModel).where(ScoringModel.version == M.VERSION))
    if model is None:
        raise SystemExit(f"No model {M.VERSION}. Run `python -m app.scoring.run` first.")
    src = STRENGTH[source]
    strength = season_strength(session, [season, season + 1], src["method"] if source == "uefa" else None)
    if not strength:
        raise SystemExit("No ClubElo data. Run `python -m ingestion.clubelo` first." if source == "clubelo" else
                         "No UEFA coefficients. Run `python -m ingestion.uefa_coefficients` first.")
    enabled = [lg.id for lg in session.scalars(select(League).where(League.enabled))]
    cal = calibrate(load_tm(session, [season, season + 1]), strength, season, enabled, unit=src["unit"])
    row = session.scalar(select(LeagueAdjustment).where(LeagueAdjustment.model_id == model.id,
                                                        LeagueAdjustment.season == season))
    values = {k: v for k, v in asdict(cal).items() if k not in ("season", "league_strength")}
    values["details"] = {"league_strength": cal.league_strength, "bootstrap": BOOTSTRAP, "min_movers": MIN_MOVERS,
                         "roles": list(CALIBRATION_ROLES), "strength": source, "unit": src["label"]}
    values["computed_at"] = datetime.now(timezone.utc)
    if row is None:
        session.add(LeagueAdjustment(model_id=model.id, season=season, **values))
    else:
        for k, v in values.items():
            setattr(row, k, v)
    session.flush()
    return cal, apply(session, model, season)


def print_report(cal: Calibration, adjusted: int, names: dict, source: str = "clubelo") -> None:
    label = STRENGTH[source]["label"]
    print(f"\nLeague-strength calibration, season {cal.season}/{str(cal.season + 1)[2:]} -> "
          f"{cal.season + 1}/{str(cal.season + 2)[2:]}")
    what = "mean ClubElo" if source == "clubelo" else "UEFA season points"
    print(f"  League strength ({what}, mean of both seasons): " +
          ", ".join(f"{names.get(k, k)} {v:g}" for k, v in sorted(cal.league_strength.items(), key=lambda kv: -kv[1])))
    print(f"  Players with >= 900 minutes in both seasons (ST/AW): {cal.n_movers} movers, {cal.n_stayers} stayers")
    if cal.beta is not None:
        print(f"  beta = {cal.beta:+.3f} probit units per {label}   95% CI [{cal.ci_low:+.3f}, {cal.ci_high:+.3f}]"
              f"   (alpha = {cal.alpha:+.3f})")
    print(f"  Decision: {'USE the adjustment' if cal.accepted else 'do NOT adjust'} - {cal.reason}")
    print(f"  Adjusted scores written: {adjusted}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Calibrate and apply the league-strength adjustment")
    parser.add_argument("--season", type=int, default=2024)
    parser.add_argument("--strength", choices=sorted(STRENGTH), default="clubelo",
                        help="league strength source: clubelo (mean club Elo) or uefa (association season points)")
    args = parser.parse_args()
    with SessionLocal() as session:
        try:
            cal, adjusted = run(session, args.season, args.strength)
            session.commit()
        except BaseException:
            session.rollback()
            raise
        names = dict(session.execute(select(League.id, League.name)).all())
    print_report(cal, adjusted, names, args.strength)


if __name__ == "__main__":
    main()
