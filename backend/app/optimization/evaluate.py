"""Optimizer evaluation for the report (Phase 5 model document, "Baselines and verification").

Runs the optimizer and the three baselines on the SAME real candidates and constraints over a
grid of formations, position requests and budgets, and measures solve time by pool size.

Usage (inside the backend container):
    python -m app.optimization.evaluate
Writes reports/optimizer_eval_<model>_<date>.json and prints a summary.
"""

import json
import random
import statistics
import time
from datetime import date
from pathlib import Path

from app.db.session import SessionLocal
from app.optimization.baselines import best_affordable_per_position, greedy_value, random_feasible
from app.optimization.candidates import load_candidates
from app.optimization.diagnose import fmt_eur
from app.optimization.model import FORMATIONS, formation_request, positions_request
from app.optimization.solver import solve
from app.scoring import model_v1 as M

REPORT_DIR = Path(__file__).resolve().parents[2] / "reports"
XI_BUDGETS = [5, 10, 15, 25, 50, 100, 200]          # EUR m
NEEDS = {"ST+CM+CB": {"ST": 1, "CM": 1, "CB": 1}, "2CM+ST": {"CM": 2, "ST": 1},
         "GK+2CB": {"GK": 1, "CB": 2}, "2AW+ST": {"AW": 2, "ST": 1}}
NEEDS_BUDGETS = [0.5, 1, 2, 5, 10, 20]             # EUR m
BASELINES = {"best_per_position": best_affordable_per_position, "greedy_value": greedy_value,
             "random_100": random_feasible}
POOL_SIZES = [250, 500, 1000, 2000]


def run_scenario(candidates, label: str, req) -> dict:
    sol = solve(candidates, req, diagnose_on_failure=False)
    row = {"scenario": label, "budget": req.budget, "status": sol.status, "solve_ms": sol.solve_time_ms,
           "eligible": sol.candidates_considered}
    if sol.team is None:
        return row
    row["optimizer"] = sol.team.total_score
    row["optimizer_cost"] = sol.team.cost
    for name, method in BASELINES.items():
        t = method(candidates, req)
        row[name] = None if t is None else t.total_score
    return row


def summarise(rows: list[dict]) -> dict:
    feasible = [r for r in rows if r.get("optimizer") is not None]
    out = {"scenarios": len(rows), "feasible": len(feasible)}
    for name in BASELINES:
        found = [r for r in feasible if r[name] is not None]
        gaps = [r["optimizer"] - r[name] for r in found]
        pct = [100 * (r["optimizer"] - r[name]) / r[name] for r in found if r[name]]
        out[name] = {
            "baseline_found_no_team": len(feasible) - len(found),
            "optimizer_strictly_better": sum(g > 1e-6 for g in gaps),
            "ties": sum(abs(g) <= 1e-6 for g in gaps),
            "baseline_better": sum(g < -1e-6 for g in gaps),   # must be 0
            "mean_gap_points": round(statistics.mean(gaps), 1) if gaps else None,
            "mean_gap_percent": round(statistics.mean(pct), 1) if pct else None,
            "max_gap_points": round(max(gaps), 1) if gaps else None,
        }
    return out


def timing(candidates, rng: random.Random, repeats: int = 5) -> list[dict]:
    out = []
    for size in [s for s in POOL_SIZES if s < len(candidates)] + [len(candidates)]:
        times = []
        for _ in range(repeats):
            sample = rng.sample(candidates, size)
            start = time.perf_counter()
            solve(sample, formation_request("4-3-3", 30_000_000, alternatives=0), diagnose_on_failure=False)
            times.append((time.perf_counter() - start) * 1000)
        out.append({"pool": size, "median_ms": round(statistics.median(times), 1), "max_ms": round(max(times), 1)})
    return out


def main() -> None:
    with SessionLocal() as session:
        candidates = load_candidates(session, 2024)
    rng = random.Random(2024)
    xi = [run_scenario(candidates, f"XI {f}", formation_request(f, b * 1_000_000, alternatives=0, min_minutes_next=900))
          for f in FORMATIONS for b in XI_BUDGETS]
    needs = [run_scenario(candidates, f"signings {label}",
                          positions_request(n, int(b * 1_000_000), alternatives=0, min_minutes_next=900))
             for label, n in NEEDS.items() for b in NEEDS_BUDGETS]
    report = {"model": M.VERSION, "date": date.today().isoformat(), "candidates": len(candidates),
              "filters": "900+ minutes 2024/25, 900+ minutes 2025/26",
              "starting_xi": summarise(xi), "signings": summarise(needs), "timing": timing(candidates, rng),
              "rows": xi + needs}

    print(f"\nOptimizer evaluation, scoring model {M.VERSION}, {len(candidates)} candidates")
    for title, key in (("Starting XI (5 formations x 7 budgets)", "starting_xi"),
                       ("Signings (4 requests x 6 budgets)", "signings")):
        s = report[key]
        print(f"\n  {title}: {s['feasible']} of {s['scenarios']} feasible")
        for name in BASELINES:
            b = s[name]
            gap = (f"mean gap +{b['mean_gap_points']} pts ({b['mean_gap_percent']}%), max +{b['max_gap_points']}"
                   if b["mean_gap_points"] is not None else "no comparable teams")
            print(f"    vs {name:<18} optimizer better {b['optimizer_strictly_better']}, ties {b['ties']}, "
                  f"baseline better {b['baseline_better']}, baseline failed {b['baseline_found_no_team']}; {gap}")
    infeasible: dict[str, list[str]] = {}
    for r in xi + needs:
        if r.get("optimizer") is None:
            infeasible.setdefault(r["scenario"], []).append(fmt_eur(r["budget"]))
    if infeasible:
        print("\n  No valid team exists for:")
        for label, budgets in infeasible.items():
            print(f"    {label:<22} at {', '.join(budgets)}")
    print("\n  Solve time by pool size (4-3-3, EUR 30m, median of 5):")
    for t in report["timing"]:
        print(f"    {t['pool']:>5} players: {t['median_ms']:>7.1f} ms (max {t['max_ms']:.1f})")

    REPORT_DIR.mkdir(exist_ok=True)
    path = REPORT_DIR / f"optimizer_eval_{M.VERSION}_{report['date']}.json"
    path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(f"\n  Saved: backend/reports/{path.name}")


if __name__ == "__main__":
    main()
