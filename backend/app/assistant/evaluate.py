"""Measure the assistant on labelled requests (FR-15, evaluation).

    python -m app.assistant.evaluate            # rules only
    python -m app.assistant.evaluate --ai       # also the AI parser (needs ANTHROPIC_API_KEY with credit)

Two sets: 'tuning' (the 40 requests the rules were developed on, so they score high by construction)
and 'holdout' (20 requests written afterwards and never used to change the rules: the honest number).
A request counts as correct only if every filter matches; field accuracy shows partial credit.
"""

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from app.assistant import llm, rules
from app.assistant.filters import AssistantFilters
from app.core.config import get_settings

FIXTURES = Path(__file__).resolve().parents[2] / "tests" / "fixtures"
FIELDS = list(AssistantFilters.model_fields)


def _score(got: AssistantFilters, want: AssistantFilters) -> tuple[bool, int]:
    g, w = got.model_dump(), want.model_dump()
    g["nationalities"], w["nationalities"] = sorted(g["nationalities"]), sorted(w["nationalities"])
    right = sum(1 for k in FIELDS if g[k] == w[k])
    return right == len(FIELDS), right


def run_set(name: str, engine: str) -> dict:
    cases = json.loads((FIXTURES / f"assistant_{name}.json").read_text(encoding="utf-8"))
    settings = get_settings()
    exact, fields, misses, failures, seconds = 0, 0, [], 0, 0.0
    for case in cases:
        want = AssistantFilters(**case["expect"])
        t0 = time.perf_counter()
        try:
            got = rules.parse(case["text"])[0] if engine == "rules" else llm.parse(
                case["text"], settings.anthropic_api_key, settings.assistant_model)
        except llm.LLMUnavailable as e:
            failures += 1
            misses.append({"text": case["text"], "error": str(e)})
            continue
        finally:
            seconds += time.perf_counter() - t0
        ok, right = _score(got, want)
        exact += ok
        fields += right
        if not ok:
            g, w = got.model_dump(), want.model_dump()
            misses.append({"text": case["text"], "wrong": {k: {"got": g[k], "expected": w[k]} for k in FIELDS if g[k] != w[k]}})
    n = len(cases)
    return {"set": name, "engine": engine, "requests": n, "exact": exact, "exact_rate": round(exact / n, 3),
            "field_accuracy": round(fields / (n * len(FIELDS)), 3), "errors": failures,
            "avg_ms": round(1000 * seconds / n, 1), "misses": misses}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ai", action="store_true", help="also evaluate the AI parser")
    args = ap.parse_args()
    engines = ["rules"] + (["ai"] if args.ai else [])
    if args.ai and not get_settings().anthropic_api_key:
        raise SystemExit("--ai needs ANTHROPIC_API_KEY in .env")
    results = [run_set(s, e) for e in engines for s in ("tuning", "holdout")]
    print("Assistant evaluation (a request is correct only if every filter matches)")
    for r in results:
        print(f"  {r['engine']:<6} {r['set']:<8} {r['exact']:>2}/{r['requests']} correct ({r['exact_rate']:.0%}), "
              f"field accuracy {r['field_accuracy']:.0%}, {r['avg_ms']} ms per request"
              + (f", {r['errors']} errors" if r["errors"] else ""))
    for r in results:
        if r["set"] == "holdout" and r["misses"]:
            print(f"\n  {r['engine']} misses on the holdout set:")
            for m in r["misses"]:
                print(f"    - {m['text']}")
                for k, v in m.get("wrong", {}).items():
                    print(f"        {k}: got {v['got']}, expected {v['expected']}")
                if "error" in m:
                    print(f"        error: {m['error']}")
    out = Path("reports") / f"assistant_eval_{datetime.now(timezone.utc):%Y%m%d_%H%M%S}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps({"created": datetime.now(timezone.utc).isoformat(), "results": results}, indent=2,
                              ensure_ascii=False), encoding="utf-8")
    print(f"\nSaved {out}")


if __name__ == "__main__":
    main()
