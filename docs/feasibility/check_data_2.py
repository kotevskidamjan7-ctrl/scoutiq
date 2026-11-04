"""
ScoutIQ - Phase 1b follow-up checks.

  A. Is page 4 of /players really blocked on the free plan, and who is on the later pages?
     (Uses 3 API-Football requests. Pages 2-4 for team 33, season 2024.)
  B. How many players per target league have a Transfermarkt market value, and how recent?
     (No API requests - reads the local DuckDB file.)
"""

import json
import os
import sys
from pathlib import Path

import duckdb
import requests
from dotenv import load_dotenv

load_dotenv()
API_KEY = os.getenv("API_FOOTBALL_KEY")
BASE_URL = "https://v3.football.api-sports.io"
DUCKDB_FILE = Path("data/transfermarkt-datasets.duckdb")
RAW_DIR = Path("raw")
RAW_DIR.mkdir(exist_ok=True)

TARGET_TM_LEAGUES = ["GB1", "ES1", "IT1", "L1", "FR1",   # v1
                     "PO1", "NL1", "BE1", "TR1",         # v1.5
                     "A1", "C1", "PL1", "KR1", "SER1"]   # v2


def check_later_pages() -> None:
    print("\nA) /players paging, team 33, season 2024")
    for page in (2, 3, 4):
        resp = requests.get(
            f"{BASE_URL}/players",
            headers={"x-apisports-key": API_KEY},
            params={"team": 33, "season": 2024, "page": page},
            timeout=30,
        )
        data = resp.json()
        (RAW_DIR / f"players_team33_p{page}.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
        left = resp.headers.get("x-ratelimit-requests-remaining", "?")
        print(f"   Page {page}: HTTP {resp.status_code}, requests left: {left}")
        if data.get("errors"):
            print(f"   API errors: {data['errors']}")
            continue
        for item in data.get("response") or []:
            name = item["player"]["name"]
            # Sum minutes over all competitions returned for this player
            minutes = sum((s["games"].get("minutes") or 0) for s in item.get("statistics", []))
            comps = ", ".join(s["league"]["name"] for s in item.get("statistics", []))
            print(f"     {name:<28} minutes={minutes:<5} [{comps}]")


def check_valuation_coverage() -> None:
    print("\nB) Transfermarkt valuation coverage per league")
    con = duckdb.connect(str(DUCKDB_FILE), read_only=True)
    print("   players columns:", [r[0] for r in con.execute("DESCRIBE players").fetchall()])
    leagues = ", ".join(f"'{c}'" for c in TARGET_TM_LEAGUES)
    try:
        rows = con.execute(f"""
            SELECT current_club_domestic_competition_id AS league,
                   count(*)                              AS players,
                   count(market_value_in_eur)            AS with_value,
                   median(market_value_in_eur)           AS median_value_eur,
                   max(last_season)                      AS latest_season
            FROM players
            WHERE current_club_domestic_competition_id IN ({leagues})
              AND last_season >= 2024
            GROUP BY 1
            ORDER BY 1
        """).fetchall()
        print(f"   {'league':<6} {'players':>8} {'with value':>11} {'median EUR':>12} {'latest season':>14}")
        for league, players, with_value, median_value, latest in rows:
            median_text = f"{median_value:,.0f}" if median_value is not None else "-"
            print(f"   {league:<6} {players:>8} {with_value:>11} {median_text:>12} {latest:>14}")
    except duckdb.Error as exc:
        print(f"   Query failed: {exc}")
        print("   Paste the column list above and I'll adjust the query.")
    con.close()


if __name__ == "__main__":
    if not API_KEY:
        sys.exit("API_FOOTBALL_KEY is missing from .env")
    check_later_pages()
    check_valuation_coverage()
    print("\nDone. Paste the output back to Claude.")
