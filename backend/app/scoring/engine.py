"""Scoring engine: pure functions on pandas DataFrames (no database access).

score_group() scores ONE league + season + role, exactly as described in the
Phase 4 methodology: coverage rule -> per-90 / rates with shrinkage ->
percentiles vs. regulars -> weighted composite -> 0-100 score -> reliability.
"""

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from app.scoring import model_v1 as M


@dataclass
class GroupResult:
    scores: pd.DataFrame                       # one row per scored player
    coverage: list[dict] = field(default_factory=list)
    available_metrics: list[str] = field(default_factory=list)
    dropped_metrics: list[str] = field(default_factory=list)
    reference_size: int = 0
    skipped_reason: str | None = None


def midrank_percentile(values: np.ndarray, reference: np.ndarray) -> np.ndarray:
    """Share of the reference strictly below each value, plus half of the ties (0..1)."""
    ref = np.sort(np.round(reference.astype(float), 9))
    vals = np.round(values.astype(float), 9)
    below = np.searchsorted(ref, vals, side="left")
    at_or_below = np.searchsorted(ref, vals, side="right")
    return (below + 0.5 * (at_or_below - below)) / len(ref)


def field_coverage(ref: pd.DataFrame, fields: list[str]) -> dict[str, float]:
    return {f: float(ref[f].notna().mean()) if f in ref and len(ref) else 0.0 for f in fields}


def _sum_fields(df: pd.DataFrame, names: tuple[str, ...], multipliers=None) -> pd.Series:
    total = pd.Series(0.0, index=df.index)
    for i, name in enumerate(names):
        total = total + df[name].astype(float) * (multipliers[i] if multipliers else 1)
    return total


def compute_metric(df: pd.DataFrame, metric: M.Metric, ref_mask: pd.Series) -> pd.Series:
    """Shrunk per-90 value or shrunk success rate for every row (fields already null-filled)."""
    minutes = df["minutes"].astype(float)
    num = _sum_fields(df, metric.plus, metric.weights_in_sum) - _sum_fields(df, metric.minus)
    num = num.clip(lower=0)
    if metric.kind == "per90":
        mu = num[ref_mask].sum() / minutes[ref_mask].sum() * 90  # pooled reference rate per 90
        m0 = M.SHRINK_MINUTES
        return (num + m0 / 90 * mu) / ((minutes + m0) / 90)
    # rate
    attempts = (_sum_fields(df, metric.attempts_plus) - _sum_fields(df, metric.attempts_minus)).clip(lower=0)
    attempts = np.maximum(attempts, num)  # successes can never exceed attempts
    ref_attempts = attempts[ref_mask].sum()
    if ref_attempts == 0:
        return pd.Series(np.nan, index=df.index)
    r_bar = num[ref_mask].sum() / ref_attempts
    return (num + metric.k * r_bar) / (attempts + metric.k)


def score_group(df: pd.DataFrame, role: str) -> GroupResult:
    """df: one league-season-role, columns player_id, minutes and the stat fields (NULL as NaN)."""
    weights = M.WEIGHTS[role]
    df = df[df["minutes"].fillna(0) >= M.MIN_SCORED_MINUTES].copy()
    ref_mask = df["minutes"] >= M.REFERENCE_MINUTES
    n_ref = int(ref_mask.sum())
    if n_ref < M.MIN_REFERENCE_PLAYERS:
        return GroupResult(scores=df.iloc[0:0], reference_size=n_ref,
                           skipped_reason=f"only {n_ref} regulars (minimum {M.MIN_REFERENCE_PLAYERS})")

    # 1. coverage rule, per field used by this role
    used_fields = sorted({f for m in weights for f in M.METRICS[m].plus + M.METRICS[m].minus
                          + M.METRICS[m].attempts_plus + M.METRICS[m].attempts_minus})
    cov = field_coverage(df[ref_mask], used_fields)
    recorded = {f: c >= M.COVERAGE_RECORDED for f, c in cov.items()}
    coverage_rows = [{"field": f, "coverage": round(c, 4), "recorded": recorded[f], "regulars": n_ref} for f, c in cov.items()]
    for f in used_fields:
        df[f] = df[f].astype(float).fillna(0.0)  # recorded: NULL = 0 events; optional & unrecorded: 0 by definition

    # 2. metrics, percentiles
    available, dropped = [], []
    pct = pd.DataFrame(index=df.index)
    values = pd.DataFrame(index=df.index)
    for name in weights:
        metric = M.METRICS[name]
        if not all(recorded[f] for f in metric.required):
            dropped.append(name)
            continue
        v = compute_metric(df, metric, ref_mask)
        if v.isna().all():
            dropped.append(name)
            continue
        p = midrank_percentile(v.to_numpy(), v[ref_mask].to_numpy())
        pct[name] = 1 - p if metric.lower_is_better else p
        values[name] = v
        available.append(name)

    if not available:
        return GroupResult(scores=df.iloc[0:0], coverage=coverage_rows, dropped_metrics=dropped,
                           reference_size=n_ref, skipped_reason="no metric recorded for this role")

    # 3. composite and 0-100 score
    w = pd.Series({n: weights[n] for n in available})
    weight_coverage = float(w.sum())  # share of the role's full weight that is available
    composite = (pct[available] * w).sum(axis=1) / weight_coverage
    score = 100 * midrank_percentile(composite.to_numpy(), composite[ref_mask].to_numpy())

    minutes = df["minutes"]
    reliability = np.select(
        [minutes >= M.HIGH_RELIABILITY_MINUTES, minutes >= M.REFERENCE_MINUTES], ["high", "medium"], "low"
    )
    if weight_coverage < M.MIN_WEIGHT_COVERAGE:
        reliability = np.full(len(df), "low")

    eff_w = (w / weight_coverage).round(4)
    breakdown = [
        {
            "minutes": int(m),
            "weight_coverage": round(weight_coverage, 4),
            "dropped": dropped,
            "metrics": {
                n: {"value": round(float(values.at[idx, n]), 4),
                    "percentile": round(float(pct.at[idx, n]) * 100, 1),
                    "weight": float(eff_w[n])}
                for n in available
            },
        }
        for idx, m in zip(df.index, minutes)
    ]
    out = pd.DataFrame({
        "player_id": df["player_id"].to_numpy(),
        "minutes": minutes.to_numpy(),
        "composite": composite.round(6).to_numpy(),
        "score": np.round(score, 1),
        "reliability": reliability,
        "breakdown": breakdown,
    })
    return GroupResult(scores=out, coverage=coverage_rows, available_metrics=available,
                       dropped_metrics=dropped, reference_size=n_ref)


# ---------- value for money ----------

def value_for_money(df: pd.DataFrame, min_points: int = 20) -> tuple[pd.Series, float | None]:
    """Score minus the score expected at this market value for this role (within-league variant).

    df columns: score, value_eur, league_id, minutes. Fitted on regulars with a value:
        score ~ a + b*ln(value) + league dummies   (ordinary least squares)
    Returns (VfM per row, R^2 of the fit). VfM is NaN if no value or too few points to fit.
    """
    result = pd.Series(np.nan, index=df.index)
    has_value = df["value_eur"].notna() & (df["value_eur"] > 0)
    fit = df[has_value & (df["minutes"] >= M.REFERENCE_MINUTES)]
    if len(fit) < min_points:
        return result, None
    leagues = sorted(fit["league_id"].unique())

    def design(frame: pd.DataFrame) -> np.ndarray:
        cols = [np.ones(len(frame)), np.log(frame["value_eur"].astype(float))]
        cols += [(frame["league_id"] == lg).astype(float).to_numpy() for lg in leagues[1:]]
        return np.column_stack(cols)

    y = fit["score"].to_numpy(dtype=float)
    coef, *_ = np.linalg.lstsq(design(fit), y, rcond=None)
    r2 = float(1 - (y - design(fit) @ coef).var() / y.var()) if y.var() > 0 else 0.0
    target = df[has_value & df["league_id"].isin(leagues)]
    result.loc[target.index] = np.round(target["score"].to_numpy(dtype=float) - design(target) @ coef, 1)
    return result, r2
