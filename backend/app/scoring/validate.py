"""Validation report for the scouting score (methodology section "Validation").

Usage (inside the backend container):
    python -m app.scoring.validate                 # season 2024, prints the report
    python -m app.scoring.validate --draws 1000    # weight-sensitivity draws (default 1000)

Also writes reports/validation_<model>_<season>.json for the project report.
All correlations are Spearman rank correlations (computed as Pearson on ranks).
"""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models import DataSource, League, PlayerSeasonStats, ScoringModel, ScoutingScore
from app.scoring import model_v1 as M

REPORT_DIR = Path(__file__).resolve().parents[2] / "reports"
MIN_GROUP = 8


def spearman(a: pd.Series, b: pd.Series) -> float | None:
    both = pd.concat([a, b], axis=1).dropna()
    if len(both) < MIN_GROUP or both.iloc[:, 0].nunique() < 2 or both.iloc[:, 1].nunique() < 2:
        return None
    return float(both.iloc[:, 0].rank().corr(both.iloc[:, 1].rank()))


def summarise(values: list[float]) -> dict:
    vals = [v for v in values if v is not None and not np.isnan(v)]
    if not vals:
        return {"groups": 0}
    return {"groups": len(vals), "median": round(float(np.median(vals)), 3),
            "min": round(float(np.min(vals)), 3), "max": round(float(np.max(vals)), 3)}


# ---------- 1 + 2: weight sensitivity and equal weights (from stored per-metric percentiles) ----------

def percentile_matrix(group: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    metrics = group["breakdown"].iloc[0]["metrics"]
    names = list(metrics)
    pct = pd.DataFrame([[b["metrics"][n]["percentile"] for n in names] for b in group["breakdown"]], columns=names)
    weights = pd.Series({n: metrics[n]["weight"] for n in names})
    return pct, weights


def weight_sensitivity(scores: pd.DataFrame, draws: int, rng: np.random.Generator) -> dict:
    per_group, equal = [], []
    for _, group in scores.groupby(["league_id", "role"]):
        if len(group) < MIN_GROUP:
            continue
        pct, w = percentile_matrix(group.reset_index(drop=True))
        base = pd.Series(pct.to_numpy() @ w.to_numpy())
        rhos = []
        for _ in range(draws):
            wp = w.to_numpy() * rng.uniform(0.8, 1.2, size=len(w))
            rhos.append(spearman(base, pd.Series(pct.to_numpy() @ (wp / wp.sum()))))
        per_group.append(float(np.median([r for r in rhos if r is not None])))
        equal.append(spearman(base, pct.mean(axis=1)))
    sens = summarise(per_group)
    sens["target"] = ">= 0.90"
    sens["passed"] = bool(per_group) and min(per_group) >= 0.90
    return {"weight_sensitivity": sens, "equal_weights": summarise(equal)}


# ---------- data for the external checks ----------

def load_scores(session: Session, model: ScoringModel, season: int) -> pd.DataFrame:
    af = session.scalar(select(DataSource).where(DataSource.code == "api_football"))
    rows = session.execute(
        select(ScoutingScore.player_id, ScoutingScore.league_id, ScoutingScore.role, ScoutingScore.score_within_league,
               ScoutingScore.value_for_money, ScoutingScore.reliability, ScoutingScore.breakdown,
               PlayerSeasonStats.rating, PlayerSeasonStats.club_id, PlayerSeasonStats.minutes)
        .join(PlayerSeasonStats, (PlayerSeasonStats.player_id == ScoutingScore.player_id)
              & (PlayerSeasonStats.league_id == ScoutingScore.league_id)
              & (PlayerSeasonStats.season == ScoutingScore.season) & (PlayerSeasonStats.source_id == af.id))
        .where(ScoutingScore.model_id == model.id, ScoutingScore.season == season)
    ).all()
    df = pd.DataFrame(rows, columns=["player_id", "league_id", "role", "score", "vfm", "reliability", "breakdown",
                                     "rating", "club_id", "minutes"])
    df["value_eur"] = [((b.get("market_value") or {}).get("value_eur")) for b in df["breakdown"]]
    df["consistent"] = [((b.get("position_check") or {}).get("consistent")) for b in df["breakdown"]]
    return df


def next_season(session: Session, season: int) -> pd.DataFrame:
    """Transfermarkt minutes, goals and assists in the FOLLOWING season, summed over supported leagues."""
    tm = session.scalar(select(DataSource).where(DataSource.code == "transfermarkt"))
    rows = session.execute(
        select(PlayerSeasonStats.player_id, func.sum(PlayerSeasonStats.minutes), func.sum(PlayerSeasonStats.goals),
               func.sum(PlayerSeasonStats.assists))
        .where(PlayerSeasonStats.source_id == tm.id, PlayerSeasonStats.season == season + 1)
        .group_by(PlayerSeasonStats.player_id)
    ).all()
    return pd.DataFrame(rows, columns=["player_id", "minutes_next", "goals_next", "assists_next"])


# ---------- 3-6 and extra checks ----------

def by_group(df: pd.DataFrame, x: str, y: str, roles=None) -> list[float]:
    out = []
    for (_, role), g in df.groupby(["league_id", "role"]):
        if roles and role not in roles:
            continue
        r = spearman(g[x], g[y])
        if r is not None:
            out.append(r)
    return out


def external_checks(df: pd.DataFrame, nxt: pd.DataFrame) -> dict:
    regulars = df[df["minutes"] >= M.REFERENCE_MINUTES].copy()
    regulars["log_value"] = np.log(regulars["value_eur"].astype(float))
    report = {
        "convergent_api_rating": summarise(by_group(regulars, "score", "rating")),
        "market_log_value": summarise(by_group(regulars, "score", "log_value")),
    }

    # predictive: next season minutes (all scored players), and attacking output for ST / AW
    merged = df.merge(nxt, on="player_id", how="left")
    merged["minutes_next"] = merged["minutes_next"].fillna(0)
    report["predictive_minutes_next"] = summarise(by_group(merged, "score", "minutes_next"))
    q = merged.groupby(["league_id", "role"])["score"].transform(lambda s: pd.qcut(s.rank(method="first"), 4, labels=False))
    report["predictive_minutes_next"]["mean_minutes_top_quartile"] = round(float(merged.loc[q == 3, "minutes_next"].mean()), 0)
    report["predictive_minutes_next"]["mean_minutes_bottom_quartile"] = round(float(merged.loc[q == 0, "minutes_next"].mean()), 0)
    attack = merged[(merged["minutes_next"] >= M.REFERENCE_MINUTES) & merged["role"].isin(["ST", "AW"])].copy()
    attack["ga90_next"] = (attack["goals_next"].fillna(0) + attack["assists_next"].fillna(0)) / attack["minutes_next"] * 90
    report["predictive_attack_ga90_next"] = summarise(by_group(attack, "score", "ga90_next", roles={"ST", "AW"}))

    # extra 1: team-strength bias (team strength proxy = mean market value of the club's regulars)
    club_value = regulars.groupby("club_id")["log_value"].mean().rename("club_log_value")
    with_club = regulars.join(club_value, on="club_id")
    report["team_strength_bias"] = {
        role: summarise(by_group(with_club, "score", "club_log_value", roles={role})) for role in M.ROLES
    }

    # extra 2: how much of the score market value explains (R^2 of the value-for-money line, per role)
    r2 = {}
    for role, g in regulars.dropna(subset=["log_value"]).groupby("role"):
        if len(g) < 20:
            continue
        X = np.column_stack([np.ones(len(g)), g["log_value"]] +
                            [(g["league_id"] == lg).astype(float) for lg in sorted(g["league_id"].unique())[1:]])
        coef, *_ = np.linalg.lstsq(X, g["score"].to_numpy(dtype=float), rcond=None)
        resid = g["score"].to_numpy(dtype=float) - X @ coef
        r2[role] = round(1 - resid.var() / g["score"].to_numpy(dtype=float).var(), 3)
    report["vfm_r2_by_role"] = r2
    report["position_mismatch"] = {"players": int((df["consistent"] == False).sum()), "of": len(df)}  # noqa: E712
    return report


def top_by_role(df: pd.DataFrame, names: dict, n: int = 10) -> dict:
    out = {}
    for (lid, role), g in df[df["minutes"] >= M.REFERENCE_MINUTES].groupby(["league_id", "role"]):
        out.setdefault(names[lid], {})[role] = g.nlargest(n, "score")["player_id"].tolist()
    return out


def validate(session: Session, season: int, draws: int, seed: int = 2024) -> dict:
    model = session.scalar(select(ScoringModel).where(ScoringModel.version == M.VERSION))
    if model is None:
        raise SystemExit(f"No scores for model {M.VERSION}. Run `python -m app.scoring.run` first.")
    df = load_scores(session, model, season)
    if df.empty:
        raise SystemExit("No scores stored for this season.")
    rng = np.random.default_rng(seed)
    report = {"model": M.VERSION, "season": season, "players": len(df),
              "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "draws": draws}
    report.update(weight_sensitivity(df, draws, rng))
    report.update(external_checks(df, next_season(session, season)))
    return report


def print_report(r: dict) -> None:
    def line(label, s, extra=""):
        if not s or not s.get("groups"):
            print(f"  {label:<44} not enough data")
            return
        print(f"  {label:<44} median {s['median']:+.2f}  (range {s['min']:+.2f} to {s['max']:+.2f}, "
              f"{s['groups']} league-role groups){extra}")

    print(f"\nValidation report, scouting score {r['model']}, season {r['season']}/{str(r['season'] + 1)[2:]}, "
          f"{r['players']} players")
    ws = r["weight_sensitivity"]
    line("1. Weight sensitivity (+-20%, rank corr.)", ws,
         f"  -> {'PASS' if ws.get('passed') else 'FAIL'} (target every group >= 0.90)")
    line("2. Agreement with equal weights", r["equal_weights"])
    line("3. Convergent: API match rating", r["convergent_api_rating"])
    line("4. Market: log market value", r["market_log_value"])
    pm = r["predictive_minutes_next"]
    line("5. Predictive: next-season league minutes", pm)
    if pm.get("groups"):
        print(f"  {'':<44} top score quartile {pm['mean_minutes_top_quartile']:.0f} min vs "
              f"bottom quartile {pm['mean_minutes_bottom_quartile']:.0f} min next season")
    line("6. Predictive: next-season G+A per 90 (ST/AW)", r["predictive_attack_ga90_next"])
    print("\n  Extra: score vs team strength (club's mean log market value); positive = favours strong teams")
    for role, s in r["team_strength_bias"].items():
        line(f"     {role}", s)
    print("\n  Extra: share of the score explained by market value (R^2 of the value-for-money line)")
    print("     " + ", ".join(f"{role} {v:.2f}" for role, v in r["vfm_r2_by_role"].items()))
    mm = r["position_mismatch"]
    print(f"\n  Position check: {mm['players']} of {mm['of']} scored players have a 2024/25 API position "
          "that differs from their role (flagged in the app)")


def main() -> None:
    parser = argparse.ArgumentParser(description="Validation report for the scouting score")
    parser.add_argument("--season", type=int, default=2024)
    parser.add_argument("--draws", type=int, default=1000)
    args = parser.parse_args()
    with SessionLocal() as session:
        report = validate(session, args.season, args.draws)
        names = dict(session.execute(select(League.id, League.name)).all())
        report["top10_player_ids"] = top_by_role(load_scores(session, session.scalar(
            select(ScoringModel).where(ScoringModel.version == M.VERSION)), args.season), names)
    print_report(report)
    REPORT_DIR.mkdir(exist_ok=True)
    path = REPORT_DIR / f"validation_{M.VERSION}_{args.season}.json"
    path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(f"\n  Saved: backend/reports/{path.name}")


if __name__ == "__main__":
    main()
