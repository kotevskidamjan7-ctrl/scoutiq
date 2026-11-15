"""Phase 9 evaluation: one command, six checks, results saved as JSON and a Markdown report.

    docker compose exec backend python -m app.evaluation.run

  E1  Optimizer: same optimum as brute force on random small problems; speed on the full data.
  E2  Score validity: does the 2024/25 score go with 2025/26 output, playing time and market value?
  E3  League adjustment: the calibration, and how well it predicts players who changed league.
  E4  Similar players: are the nearest profiles really alike (same detailed position)?
  E5  Assistant: tuning, hold-out and a fresh unseen set of requests.
  E6  Budget realism: what each budget buys, and what a EUR 500k club can do.

Everything is seeded, so a rerun on the same data gives the same numbers.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import statistics
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from itertools import combinations, product
from pathlib import Path

import numpy as np
import pandas as pd
from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import LeagueAdjustment, Player
from app.optimization.candidates import load_candidates
from app.optimization.model import FORMATIONS, ROLES, Candidate, formation_request, positions_request
from app.optimization.solver import UNIT, _score10, solve
from app.players.service import SCORED_SEASON, _model, all_rows
from app.players.similar import profiles, similar
from app.scoring import league_adjust as LA
from app.scoring import model_v1 as M

SEED = 2026
RECENT = SCORED_SEASON + 1
ROLE_NAMES = {"GK": "Goalkeeper", "CB": "Centre-back", "FB": "Full-back", "CM": "Central midfielder",
              "AW": "Attacking / wide", "ST": "Striker"}


# ---------- small statistics helpers ----------

def spearman(x, y) -> float | None:
    s = pd.DataFrame({"x": x, "y": y}).dropna()
    if len(s) < 10:
        return None
    return round(float(s["x"].rank().corr(s["y"].rank())), 3)


def spearman_ci(x, y, n_boot: int = 1000, seed: int = SEED) -> tuple[float | None, float | None, float | None]:
    """Spearman's rho with a bootstrap 95% interval."""
    s = pd.DataFrame({"x": x, "y": y}).dropna().reset_index(drop=True)
    if len(s) < 10:
        return None, None, None
    rx, ry = s["x"].rank().to_numpy(), s["y"].rank().to_numpy()
    rho = float(np.corrcoef(rx, ry)[0, 1])
    rng = np.random.default_rng(seed)
    boots = []
    for _ in range(n_boot):
        i = rng.integers(0, len(s), len(s))
        a, b = pd.Series(s["x"].to_numpy()[i]).rank(), pd.Series(s["y"].to_numpy()[i]).rank()
        if a.std() > 0 and b.std() > 0:
            boots.append(float(np.corrcoef(a, b)[0, 1]))
    lo, hi = np.percentile(boots, [2.5, 97.5]) if boots else (None, None)
    return round(rho, 3), (round(float(lo), 3) if lo is not None else None), (round(float(hi), 3) if hi is not None else None)


def eur(v: float | None) -> str:
    if v is None:
        return "–"
    return f"€{v / 1e6:.1f}m" if v >= 1e6 else f"€{v / 1e3:.0f}k"


def table(headers: list[str], rows: list[list]) -> str:
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    out += ["| " + " | ".join("–" if v is None else str(v) for v in r) + " |" for r in rows]
    return "\n".join(out)


# ---------- E1: optimizer exactness and speed ----------

def _brute_force(pool: list[Candidate], needs: dict[str, int], budget: int) -> tuple[tuple[int, int] | None, int]:
    """Best (score x10, -cost units) by trying every combination, in the solver's integer units."""
    cap = budget // UNIT
    groups = [list(combinations([c for c in pool if c.role == r], k)) for r, k in needs.items()]
    best, tried = None, 0
    for combo in product(*groups):
        tried += 1
        team = [p for g in combo for p in g]
        cost = sum(math.ceil(p.price / UNIT) for p in team)
        if cost > cap:
            continue
        key = (sum(_score10(p) for p in team), -cost)
        if best is None or key > best:
            best = key
    return best, tried


def e1_optimizer(cands: list[Candidate], cands_adj: list[Candidate], db, instances: int = 60, per_role: int = 8) -> dict:
    rng = random.Random(SEED)
    configs = [{"GK": 1, "CB": 2, "ST": 1}, {"CM": 2, "AW": 1}, {"FB": 2, "CB": 1, "CM": 1},
               {"CB": 2, "CM": 1, "ST": 1}, {"AW": 2, "ST": 1}, {"GK": 1, "FB": 1, "CM": 1, "AW": 1}]
    by_role = defaultdict(list)
    for c in cands:
        if c.minutes >= M.REFERENCE_MINUTES and c.price > 0:
            by_role[c.role].append(c)
    agree, infeasible_both, rows, combos, t_opt, t_bf = 0, 0, [], [], [], []
    for i in range(instances):
        needs = configs[i % len(configs)]
        pool = [c for r in needs for c in rng.sample(by_role[r], min(per_role, len(by_role[r])))]
        dearest = sum(sum(sorted((c.price for c in pool if c.role == r), reverse=True)[:k]) for r, k in needs.items())
        budget = int(dearest * rng.uniform(0.1, 0.8))
        req = positions_request(needs, budget, min_minutes=0, min_minutes_next=0, alternatives=0)
        t0 = time.perf_counter()
        sol = solve(pool, req, diagnose_on_failure=False)
        t_opt.append((time.perf_counter() - t0) * 1000)
        t0 = time.perf_counter()
        best, tried = _brute_force(pool, needs, budget)
        t_bf.append((time.perf_counter() - t0) * 1000)
        combos.append(tried)
        got = None
        if sol.team is not None:
            got = (sum(_score10(p) for p in sol.team.players), -sum(math.ceil(p.price / UNIT) for p in sol.team.players))
            assert sol.team.cost <= budget, "optimizer team over budget"
        ok = got == best
        agree += ok
        infeasible_both += (got is None and best is None)
        if not ok:
            rows.append({"instance": i, "needs": needs, "budget": budget, "optimizer": got, "brute_force": best})

    # speed on the full data: every formation x budget, as the app runs it
    speed = []
    for f in FORMATIONS:
        for b in (1_000_000, 5_000_000, 20_000_000, 100_000_000):
            sol = solve(cands_adj, formation_request(f, b, min_minutes_next=M.REFERENCE_MINUTES, alternatives=2))
            speed.append({"formation": f, "budget": b, "status": sol.status, "ms": sol.solve_time_ms,
                          "candidates": sol.candidates_considered, "score": sol.team.total_score if sol.team else None,
                          "violations": len(sol.violations)})
    times = [s["ms"] for s in speed]
    return {
        "instances": instances, "agree": agree, "infeasible_both": infeasible_both, "disagreements": rows,
        "combinations_per_instance": {"median": int(statistics.median(combos)), "max": max(combos)},
        "ms_optimizer_median": round(statistics.median(t_opt), 1), "ms_brute_force_median": round(statistics.median(t_bf), 1),
        "full_data": speed, "full_data_ms": {"median": round(statistics.median(times), 1), "max": round(max(times), 1)},
        "full_data_violations": sum(s["violations"] for s in speed),
    }


# ---------- E2: score validity ----------

def _tm_frame(db) -> pd.DataFrame:
    tm = LA.load_tm(db, [SCORED_SEASON, RECENT])
    tm = tm.groupby(["player_id", "season"], as_index=False).agg(
        minutes=("minutes", "sum"), goals=("goals", "sum"), assists=("assists", "sum"))
    tm["ga90"] = (tm["goals"].fillna(0) + tm["assists"].fillna(0)) / tm["minutes"].replace(0, np.nan) * 90
    return tm


def e2_validity(db, rows) -> dict:
    tm = _tm_frame(db)
    now = tm[tm["season"] == SCORED_SEASON].set_index("player_id")
    nxt = tm[tm["season"] == RECENT].set_index("player_id")
    df = pd.DataFrame([{"player_id": r.player_id, "role": r.role, "score": r.score, "reliability": r.reliability,
                        "price": r.price_eur} for r in rows])
    df = df[df["reliability"] != "low"].copy()
    df["ga90_now"] = df["player_id"].map(now["ga90"])
    df["ga90_next"] = df["player_id"].map(nxt["ga90"])
    df["min_next"] = df["player_id"].map(nxt["minutes"]).fillna(0)

    predictive = []
    for role in ("ST", "AW", "CM"):
        d = df[(df["role"] == role) & (df["min_next"] >= M.REFERENCE_MINUTES)]
        rho, lo, hi = spearman_ci(d["score"], d["ga90_next"])
        base = spearman(d["ga90_now"], d["ga90_next"])
        predictive.append({"role": role, "n": int(d["ga90_next"].notna().sum()), "rho": rho, "ci": [lo, hi],
                           "baseline_ga90_rho": base})

    playing, market = [], []
    for role in ROLES:
        d = df[df["role"] == role]
        rho, lo, hi = spearman_ci(d["score"], d["min_next"])
        q = d["score"].quantile([0.25, 0.75])
        top = d[d["score"] >= q[0.75]]["min_next"].mean()
        bottom = d[d["score"] <= q[0.25]]["min_next"].mean()
        playing.append({"role": role, "n": len(d), "rho": rho, "ci": [lo, hi],
                        "minutes_next_top_quarter": round(float(top)), "minutes_next_bottom_quarter": round(float(bottom))})
        dv = d[d["price"].notna() & (d["price"] > 0)]
        rho, lo, hi = spearman_ci(dv["score"], np.log(dv["price"].astype(float)))
        market.append({"role": role, "n": len(dv), "rho": rho, "ci": [lo, hi]})
    return {"predictive_ga90": predictive, "playing_time_next": playing, "market_value": market}


# ---------- E3: league adjustment ----------

def e3_league(db) -> dict:
    model = _model(db)
    cal = db.scalar(select(LeagueAdjustment).where(LeagueAdjustment.model_id == model.id,
                                                   LeagueAdjustment.season == SCORED_SEASON))
    if cal is None:
        return {"calibration": None}
    details = cal.details or {}
    src = LA.STRENGTH[details.get("strength", "clubelo")]
    unit = src["unit"]
    strength = LA.season_strength(db, [SCORED_SEASON, RECENT], src["method"] if src is LA.STRENGTH["uefa"] else None)
    by_league = defaultdict(list)
    for (lg, _), e in strength.items():
        by_league[lg].append(e)
    e_mean = {lg: float(np.mean(v)) for lg, v in by_league.items()}

    # main league per player-season (>= 900 min) and his goals+assists percentile there, all outfield roles
    tm = LA.load_tm(db, [SCORED_SEASON, RECENT])
    tm = tm[tm["role"].isin(["ST", "AW", "CM"]) & tm["league_id"].isin(e_mean)]
    tm = tm.sort_values("minutes", ascending=False).drop_duplicates(["player_id", "season"])
    tm = tm[tm["minutes"] >= M.REFERENCE_MINUTES].copy()
    tm["ga90"] = (tm["goals"].fillna(0) + tm["assists"].fillna(0)) / tm["minutes"] * 90
    tm["pct"] = tm.groupby(["league_id", "season", "role"])["ga90"].rank(pct=True) * 100
    a = tm[tm["season"] == SCORED_SEASON].set_index("player_id")
    b = tm[tm["season"] == RECENT].set_index("player_id")
    both = a.add_suffix("_a").join(b.add_suffix("_b"), how="inner")
    both = both[both["role_a"] == both["role_b"]]
    movers = both[both["league_id_a"] != both["league_id_b"]].copy()

    def predict(row, adjust: bool) -> float:
        p = min(max(row["pct_a"], 0.5), 99.5)
        if not adjust:
            return p
        z = LA._N.inv_cdf(p / 100) + cal.beta * (e_mean[row["league_id_b"]] - e_mean[row["league_id_a"]]) / unit
        return 100 * LA._N.cdf(z)

    out = []
    for label, roles in (("ST + AW (the calibration roles: in-sample)", ("ST", "AW")),
                         ("CM (not used in the calibration: out-of-sample)", ("CM",))):
        m = movers[movers["role_a"].isin(roles)]
        if len(m) == 0:
            out.append({"group": label, "n": 0})
            continue
        err0 = (m["pct_b"] - m.apply(lambda r: predict(r, False), axis=1)).abs()
        err1 = (m["pct_b"] - m.apply(lambda r: predict(r, True), axis=1)).abs()
        up = m[m.apply(lambda r: e_mean[r["league_id_b"]] > e_mean[r["league_id_a"]], axis=1)]
        out.append({"group": label, "n": len(m), "to_stronger_league": len(up),
                    "mae_no_adjustment": round(float(err0.mean()), 1), "mae_with_adjustment": round(float(err1.mean()), 1),
                    "mean_change_to_stronger": round(float((up["pct_b"] - up["pct_a"]).mean()), 1) if len(up) else None,
                    "mean_change_to_weaker": round(float((m.drop(up.index)["pct_b"] - m.drop(up.index)["pct_a"]).mean()), 1)
                    if len(m) > len(up) else None})
    return {
        "calibration": {"source": details.get("strength", "clubelo"), "unit": unit, "beta": round(cal.beta, 3),
                        "ci": [round(cal.ci_low, 3), round(cal.ci_high, 3)], "alpha": round(cal.alpha or 0, 3),
                        "movers": cal.n_movers, "stayers": cal.n_stayers, "accepted": cal.accepted, "reason": cal.reason},
        "league_strength": {str(k): round(v, 2) for k, v in sorted(e_mean.items(), key=lambda kv: -kv[1])},
        "movers_check": out,
    }


# ---------- E4: similar players ----------

# roles that cover several detailed Transfermarkt positions (left/right back; defensive/central/attacking
# midfield; wingers and attacking midfield). For GK, CB and ST the position check would always pass.
MULTI_POSITION_ROLES = ("FB", "CM", "AW")

def e4_similar(db, rows, sample: int = 200) -> dict:
    profs = profiles(db)
    rowmap = {r.player_id: r for r in rows}
    eligible = [pid for pid, p in profs.items() if pid in rowmap and rowmap[pid].reliability == "high"]
    rng = random.Random(SEED)
    picks = rng.sample(eligible, min(sample, len(eligible)))
    positions = dict(db.execute(select(Player.id, Player.primary_position)).all())
    by_role = defaultdict(list)
    for pid, p in profs.items():
        if pid in rowmap and rowmap[pid].reliability != "low":
            by_role[p.role].append(pid)
    same_pos, base_pos, top1, top10, score_gap, rand_gap, same_league, base_league = [], [], [], [], [], [], [], []
    for pid in picks:
        res = similar(db, pid, limit=10, preloaded=(profs, rows))
        if not res or not res["results"]:
            continue
        me = rowmap[pid]
        found = res["results"]
        top1.append(found[0]["similarity"])
        top10.append(statistics.mean(x["similarity"] for x in found))
        if profs[pid].role in MULTI_POSITION_ROLES:
            same_pos.append(statistics.mean(positions.get(x["player_id"]) == positions.get(pid) for x in found))
        same_league.append(statistics.mean(x["league_id"] == me.league_id for x in found))
        score_gap.append(statistics.mean(abs((x["score"] or 0) - me.score) for x in found))
        others = [o for o in by_role[profs[pid].role] if o != pid]
        rand = rng.sample(others, min(10, len(others)))
        if profs[pid].role in MULTI_POSITION_ROLES:
            base_pos.append(statistics.mean(positions.get(o) == positions.get(pid) for o in rand))
        base_league.append(statistics.mean(rowmap[o].league_id == me.league_id for o in rand))
        rand_gap.append(statistics.mean(abs(rowmap[o].score - me.score) for o in rand))
    n = len(top1)
    return {"players": n, "similarity_top1_mean": round(statistics.mean(top1), 1),
            "similarity_top10_mean": round(statistics.mean(top10), 1),
            "position_check_players": len(same_pos),
            "same_detailed_position": round(statistics.mean(same_pos), 3) if same_pos else None,
            "same_position_random": round(statistics.mean(base_pos), 3) if base_pos else None,
            "score_gap_similar": round(statistics.mean(score_gap), 1), "score_gap_random": round(statistics.mean(rand_gap), 1),
            "same_league_similar": round(statistics.mean(same_league), 3), "same_league_random": round(statistics.mean(base_league), 3)}


# ---------- E5: assistant ----------

def e5_assistant(with_ai: bool) -> dict:
    from app.assistant.evaluate import run_set
    sets = []
    for name in ("tuning", "holdout", "fresh"):
        sets.append(run_set(name, "rules"))
        if with_ai:
            sets.append(run_set(name, "ai"))
    return {"sets": sets}


# ---------- E6: budget realism ----------

def e6_budgets(db, cands_adj: list[Candidate], cands: list[Candidate]) -> dict:
    strength = LA.season_strength(db, [SCORED_SEASON, RECENT], "uefa_season_points")
    by_league = defaultdict(list)
    for (lg, _), e in strength.items():
        by_league[lg].append(e)
    e_mean = {lg: float(np.mean(v)) for lg, v in by_league.items()}
    budgets = (500_000, 1_000_000, 2_000_000, 5_000_000, 10_000_000, 30_000_000, 100_000_000, 300_000_000)
    rows = []
    for b in budgets:
        sol = solve(cands_adj, formation_request("4-3-3", b, min_minutes_next=M.REFERENCE_MINUTES, alternatives=0))
        if sol.team is None:
            rows.append({"budget": b, "status": sol.status, "reason": (sol.diagnosis or {}).get("reason")})
            continue
        ps = sol.team.players
        leagues = Counter(p.league for p in ps)
        rows.append({"budget": b, "status": sol.status, "score_adjusted": sol.team.total_score, "cost": sol.team.cost,
                     "max_price": max(p.price for p in ps), "median_price": int(statistics.median(p.price for p in ps)),
                     "avg_league_strength": round(statistics.mean(e_mean.get(p.league_id, float("nan")) for p in ps), 2),
                     "premier_league_players": leagues.get("Premier League", 0), "leagues": dict(leagues.most_common())})

    # the brief's small club: in every league, the club whose 2024/25 squad is worth least, with EUR 500k
    from app.api.improve import improve
    from app.players.clubs import squad
    from app.schemas.optimize import ImproveRequest
    value = defaultdict(int)
    league_of = {}
    for c in cands:
        if c.club_id:
            value[c.club_id] += c.price
            league_of[c.club_id] = c.league
    smallest = {}
    for club, v in value.items():
        lg = league_of[club]
        if lg not in smallest or v < value[smallest[lg]]:
            smallest[lg] = club
    def small_clubs(age_max: int | None) -> list[dict]:
        out = []
        for lg, club in sorted(smallest.items()):
            sq = squad(db, club)
            if not sq:
                continue
            owned = [p["player_id"] for p in sq["players"] if p["score"] is not None]
            if len(owned) < 11:
                out.append({"league": lg, "club": sq["club"]["name"], "status": "too few scored players", "owned": len(owned)})
                continue
            res = improve(ImproveRequest(formation="4-3-3", budget_eur=500_000, owned_player_ids=owned, max_signings=2,
                                         score="adjusted", age_max=age_max), db)
            if res.team is None:
                reason = (res.diagnosis.reason if res.diagnosis else "") or "no plan"
                out.append({"league": lg, "club": sq["club"]["name"], "status": f"no plan: {reason}", "owned": len(owned)})
                continue
            signings = [p for p in res.team.players if p.signing]
            out.append({"league": lg, "club": sq["club"]["name"], "owned": len(owned), "status": "ok",
                        "gain": round(res.team.total_score - res.current.total_score, 1) if res.current else None,
                        "spent": res.team.cost_eur,
                        "signings": [{"name": p.name, "league": p.league, "price": p.price_eur, "score": p.score,
                                      "age": p.age} for p in signings]})
        return out

    # squads from the data (end of 2025/26), not the live API squads, so the result is reproducible and costs nothing
    small = small_clubs(None)
    small_30 = small_clubs(30)
    return {"budgets_433": rows, "small_clubs_500k": small, "small_clubs_500k_age_max_30": small_30}


# ---------- report ----------

def markdown(r: dict) -> str:
    md = [f"# ScoutIQ evaluation\n\nRun {r['created']} on season {SCORED_SEASON}/{str(RECENT)[2:]} data "
          f"({r['data']['scored_players']} scored players, {r['data']['candidates']} with a market value). Seed {SEED}.\n"]
    e1 = r["E1"]
    md.append("## E1 Optimizer\n")
    md.append(f"**Exactness.** On {e1['instances']} random small problems built from real players (8 candidates per "
              f"position, random budget), the optimizer found the same optimum as brute force (best score, then lowest "
              f"cost) in **{e1['agree']} of {e1['instances']}** ({e1['infeasible_both']} were infeasible for both). "
              f"Brute force tried a median of {e1['combinations_per_instance']['median']:,} combinations "
              f"(max {e1['combinations_per_instance']['max']:,}); median time {e1['ms_brute_force_median']} ms vs "
              f"{e1['ms_optimizer_median']} ms for the optimizer.\n")
    md.append(f"**Speed on the full data** (all formations x EUR 1m/5m/20m/100m, two alternatives each): median "
              f"{e1['full_data_ms']['median']} ms, slowest {e1['full_data_ms']['max']} ms; independent verification found "
              f"{e1['full_data_violations']} constraint violations.\n")
    md.append(table(["Formation", "Budget", "Status", "Candidates", "XI score", "ms"],
                    [[s["formation"], eur(s["budget"]), s["status"], s["candidates"], s["score"], s["ms"]] for s in e1["full_data"]]))

    e2 = r["E2"]
    md.append("\n\n## E2 Score validity\n")
    md.append("Spearman correlations with bootstrap 95% intervals; regulars only (900+ minutes in 2024/25).\n")
    md.append("**Does the 2024/25 score go with 2025/26 goals + assists per 90?** (players with 900+ minutes in 2025/26; "
              "baseline = 2024/25 goals + assists per 90 itself)\n")
    md.append(table(["Role", "n", "rho (score)", "95% CI", "rho (baseline)"],
                    [[ROLE_NAMES[x["role"]], x["n"], x["rho"], x["ci"], x["baseline_ga90_rho"]] for x in e2["predictive_ga90"]]))
    md.append("\n\n**Do higher-scored players keep playing in 2025/26?**\n")
    md.append(table(["Role", "n", "rho (score vs 25/26 minutes)", "95% CI", "Avg min. top quarter", "Avg min. bottom quarter"],
                    [[ROLE_NAMES[x["role"]], x["n"], x["rho"], x["ci"], x["minutes_next_top_quarter"], x["minutes_next_bottom_quarter"]]
                     for x in e2["playing_time_next"]]))
    md.append("\n\n**Score vs market value** (ln value)\n")
    md.append(table(["Role", "n", "rho", "95% CI"], [[ROLE_NAMES[x["role"]], x["n"], x["rho"], x["ci"]] for x in e2["market_value"]]))

    e3 = r["E3"]
    md.append("\n\n## E3 League adjustment\n")
    c = e3.get("calibration")
    if c:
        md.append(f"Strength source: {c['source']} (unit {c['unit']}). beta = {c['beta']} per unit, 95% CI {c['ci']}, "
                  f"alpha {c['alpha']}; {c['movers']} movers, {c['stayers']} stayers. Accepted: {c['accepted']} ({c['reason']}).\n")
        md.append("**Players who changed league** (2024/25 -> 2025/26, 900+ minutes in both): error in predicting their "
                  "goals + assists percentile in the new league, without and with the adjustment.\n")
        md.append(table(["Group", "Movers", "To stronger league", "MAE no adjustment", "MAE with adjustment",
                         "Avg change, to stronger", "Avg change, to weaker"],
                        [[x["group"], x["n"], x.get("to_stronger_league"), x.get("mae_no_adjustment"), x.get("mae_with_adjustment"),
                          x.get("mean_change_to_stronger"), x.get("mean_change_to_weaker")] for x in e3["movers_check"]]))

    e4 = r["E4"]
    md.append("\n\n## E4 Similar players\n")
    md.append(f"For {e4['players']} random high-reliability players, the 10 most similar vs 10 random players of the same role:\n")
    md.append(table(["", "Similar players", "Random, same role"], [
        [f"Same detailed Transfermarkt position, e.g. left vs right back (not used by the search; "
         f"{e4['position_check_players']} full-backs, midfielders and wide players)",
         f"{100 * e4['same_detailed_position']:.0f}%" if e4["same_detailed_position"] is not None else None,
         f"{100 * e4['same_position_random']:.0f}%" if e4["same_position_random"] is not None else None],
        ["Average score difference", e4["score_gap_similar"], e4["score_gap_random"]],
        ["Same league", f"{100 * e4['same_league_similar']:.0f}%", f"{100 * e4['same_league_random']:.0f}%"],
    ]))
    md.append(f"\n\nMean similarity: closest player {e4['similarity_top1_mean']}, top ten {e4['similarity_top10_mean']}.\n")

    md.append("\n## E5 Assistant\n")
    md.append(table(["Set", "Engine", "Requests", "Exactly right", "Fields right", "Avg ms"],
                    [[s["set"], s["engine"], s["requests"], f"{s['exact']} ({100 * s['exact_rate']:.0f}%)",
                      f"{100 * s['field_accuracy']:.0f}%", s["avg_ms"]] for s in r["E5"]["sets"]]))
    md.append("\n\n'tuning' was used to build the rules; 'holdout' was kept apart (one fix made after seeing it); "
              "'fresh' was written for this evaluation and not used for any change.\n")

    e6 = r["E6"]
    md.append("\n## E6 Budget realism\n")
    md.append("**Best 4-3-3 for each budget** (league-adjusted scores, players still playing in 2025/26):\n")
    md.append(table(["Budget", "Status", "XI score", "Cost", "Dearest", "Median price", "Avg league strength (UEFA)",
                     "Premier League players", "Leagues"],
                    [[eur(x["budget"]), x["status"], x.get("score_adjusted"), eur(x.get("cost")), eur(x.get("max_price")),
                      eur(x.get("median_price")), x.get("avg_league_strength"), x.get("premier_league_players"),
                      ", ".join(f"{k} {v}" for k, v in (x.get("leagues") or {}).items()) or x.get("reason")] for x in e6["budgets_433"]]))
    def small_table(rows):
        return table(["League", "Club", "Gain", "Spent", "Signings (league, price, score, age)"],
                     [[x["league"], x["club"], x.get("gain"), eur(x.get("spent")),
                       "; ".join(f"{s['name']} ({s['league']}, {eur(s['price'])}, {s['score']}, {s.get('age', '–')})"
                                 for s in x.get("signings", [])) or x["status"]] for x in rows])

    md.append("\n\n**The smallest club in each league with EUR 500k and at most 2 signings** (squads as in the data, "
              "end of 2025/26):\n")
    md.append(small_table(e6["small_clubs_500k"]))
    ages = [s["age"] for x in e6["small_clubs_500k"] for s in x.get("signings", []) if s.get("age") is not None]
    if ages:
        md.append(f"\n\nAverage age of these signings: {statistics.mean(ages):.1f}. Old players have low market values but "
                  "can still have strong 2024/25 statistics; the score does not model age. **The same with an oldest age "
                  "of 30** (the existing filter):\n")
        md.append(small_table(e6["small_clubs_500k_age_max_30"]))
    return "\n".join(md) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description="Run the ScoutIQ evaluation (Phase 9)")
    ap.add_argument("--ai", action="store_true", help="also evaluate the Claude-based assistant (needs ANTHROPIC_API_KEY)")
    ap.add_argument("--only", nargs="*", choices=["E1", "E2", "E3", "E4", "E5", "E6"], help="run only these checks")
    args = ap.parse_args()
    run = set(args.only or ["E1", "E2", "E3", "E4", "E5", "E6"])
    db = SessionLocal()
    t0 = time.perf_counter()
    cands = load_candidates(db, SCORED_SEASON, "within")
    cands_adj = load_candidates(db, SCORED_SEASON, "adjusted")
    rows = all_rows(db)
    result = {"created": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
              "data": {"scored_players": len(rows), "candidates": len(cands)}}
    steps = [("E1", lambda: e1_optimizer(cands, cands_adj, db)), ("E2", lambda: e2_validity(db, rows)),
             ("E3", lambda: e3_league(db)), ("E4", lambda: e4_similar(db, rows)),
             ("E5", lambda: e5_assistant(args.ai)), ("E6", lambda: e6_budgets(db, cands_adj, cands))]
    for key, fn in steps:
        if key in run:
            t = time.perf_counter()
            print(f"{key} ...", end=" ", flush=True)
            result[key] = fn()
            print(f"done in {time.perf_counter() - t:.1f} s")
    out_dir = Path("reports")
    out_dir.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    (out_dir / f"evaluation_{stamp}.json").write_text(json.dumps(result, indent=2, default=str, ensure_ascii=False), encoding="utf-8")
    if run == {"E1", "E2", "E3", "E4", "E5", "E6"}:
        text = markdown(result)
        (out_dir / f"evaluation_{stamp}.md").write_text(text, encoding="utf-8")
        print("\n" + text)
    print(f"Saved reports/evaluation_{stamp}.json" + (f" and .md" if run == {"E1", "E2", "E3", "E4", "E5", "E6"} else "")
          + f"  ({time.perf_counter() - t0:.0f} s in total)")


if __name__ == "__main__":
    main()
