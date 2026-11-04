"""
ScoutIQ - Phase 1b data verification spike.

Checks, without building any app code:
  1. Your API-Football key works and which plan it is on.
  2. Player-statistics coverage for the top 5 leagues, season 2024 (= 2024/25).
  3. Whether per-team /players queries return a full squad within the free 3-page cap.
  4. What the Transfermarkt DuckDB snapshot contains (leagues, latest valuation date).

Uses about 9 API-Football requests out of your 100/day.
Every raw API response is saved to raw/ so we never need to re-request it.
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
SEASON = 2024
DUCKDB_FILE = Path("data/transfermarkt-datasets.duckdb")
RAW_DIR = Path("raw")
RAW_DIR.mkdir(exist_ok=True)

# API-Football league IDs for the top 5 leagues
TOP5 = {
    "Premier League": 39,
    "La Liga": 140,
    "Serie A": 135,
    "Bundesliga": 78,
    "Ligue 1": 61,
}
SAMPLE_TEAM_ID = 33  # Manchester United, used to test squad paging


def api_get(endpoint: str, params: dict, save_as: str) -> dict:
    """Call API-Football once, save the raw JSON, print remaining quota."""
    resp = requests.get(
        f"{BASE_URL}/{endpoint}",
        headers={"x-apisports-key": API_KEY},
        params=params,
        timeout=30,
    )
    data = resp.json()
    (RAW_DIR / f"{save_as}.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
    remaining = resp.headers.get("x-ratelimit-requests-remaining", "?")
    print(f"   [{endpoint} {params}] HTTP {resp.status_code}, requests left today: {remaining}")
    if data.get("errors"):
        print(f"   API errors: {data['errors']}")
    return data


def check_account() -> None:
    print("\n1) Account status")
    data = api_get("status", {}, "status")
    resp = data.get("response") or {}
    if isinstance(resp, dict):
        print(f"   Plan: {resp.get('subscription', {}).get('plan')}")
        print(f"   Requests: {resp.get('requests')}")


def check_league_coverage() -> None:
    print(f"\n2) Coverage for season {SEASON} (= {SEASON}/{str(SEASON + 1)[2:]})")
    for name, league_id in TOP5.items():
        data = api_get("leagues", {"id": league_id, "season": SEASON}, f"league_{league_id}_{SEASON}")
        items = data.get("response") or []
        if not items:
            print(f"   {name}: no data returned")
            continue
        for season in items[0].get("seasons", []):
            if season.get("year") == SEASON:
                cov = season.get("coverage", {})
                fixtures_cov = cov.get("fixtures", {})
                print(
                    f"   {name}: players={cov.get('players')}, "
                    f"statistics_players={fixtures_cov.get('statistics_players')}"
                )


def check_squad_paging() -> None:
    print(f"\n3) Squad paging test: team {SAMPLE_TEAM_ID}, season {SEASON}")
    page1 = api_get("players", {"team": SAMPLE_TEAM_ID, "season": SEASON, "page": 1}, "players_team33_p1")
    paging = page1.get("paging", {})
    total_pages = paging.get("total", 0)
    count = len(page1.get("response") or [])
    print(f"   Page 1: {count} players, total pages: {total_pages}")
    if total_pages and total_pages > 3:
        print("   WARNING: more than 3 pages - free cap would cut this squad off")
    elif total_pages:
        print("   OK: whole squad fits within the free 3-page cap")

    # Print the stat fields of the first player so we can freeze our schema
    first = (page1.get("response") or [None])[0]
    if first and first.get("statistics"):
        print("   Statistic groups returned for one player:")
        for group, values in first["statistics"][0].items():
            if isinstance(values, dict):
                print(f"     {group}: {list(values.keys())}")


def check_transfermarkt() -> None:
    print(f"\n4) Transfermarkt snapshot: {DUCKDB_FILE}")
    if not DUCKDB_FILE.exists():
        print("   File not found - download it into the data/ folder first.")
        return
    con = duckdb.connect(str(DUCKDB_FILE), read_only=True)
    print("   Tables:", [row[0] for row in con.execute("SHOW TABLES").fetchall()])
    print("   competitions columns:", [row[0] for row in con.execute("DESCRIBE competitions").fetchall()])
    try:
        rows = con.execute(
            "SELECT * FROM competitions WHERE type ILIKE '%domestic_league%' ORDER BY 1"
        ).fetchall()
        print(f"   Domestic leagues ({len(rows)}):")
        for row in rows:
            print("    ", row)
    except duckdb.Error as exc:
        print(f"   Could not filter by type ({exc}); listing all competitions instead")
        for row in con.execute("SELECT * FROM competitions").fetchall():
            print("    ", row)
    latest = con.execute("SELECT max(date) FROM player_valuations").fetchone()[0]
    print(f"   Latest valuation date: {latest}")
    con.close()


if __name__ == "__main__":
    if not API_KEY:
        sys.exit("API_FOOTBALL_KEY is missing. Put it in a .env file next to this script.")
    check_account()
    check_league_coverage()
    check_squad_paging()
    check_transfermarkt()
    print("\nDone. Copy everything above (it contains no API key) and paste it back to Claude.")
