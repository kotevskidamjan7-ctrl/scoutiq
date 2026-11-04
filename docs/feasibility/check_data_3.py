"""
ScoutIQ - Phase 1b: Transfermarkt valuation coverage per league.
Reads only the local DuckDB file (uses no API-Football requests).

Fix vs. check_data_2.py: players.last_season is stored as text, so it is cast to an integer.
"""

from pathlib import Path

import duckdb

DUCKDB_FILE = Path("data/transfermarkt-datasets.duckdb")

TARGET_TM_LEAGUES = ["GB1", "ES1", "IT1", "L1", "FR1",   # v1
                     "PO1", "NL1", "BE1", "TR1",         # v1.5
                     "A1", "C1", "PL1", "KR1", "SER1"]   # v2

con = duckdb.connect(str(DUCKDB_FILE), read_only=True)
leagues = ", ".join(f"'{c}'" for c in TARGET_TM_LEAGUES)

print("players.last_season sample values:",
      [r[0] for r in con.execute("SELECT DISTINCT last_season FROM players ORDER BY 1 DESC LIMIT 5").fetchall()])

rows = con.execute(f"""
    WITH latest_valuation AS (
        SELECT player_id, max(date) AS last_valuation_date
        FROM player_valuations
        GROUP BY player_id
    )
    SELECT p.current_club_domestic_competition_id               AS league,
           count(*)                                             AS players,
           count(p.market_value_in_eur)                         AS with_value,
           count(*) FILTER (WHERE lv.last_valuation_date >= DATE '2025-07-01') AS valued_since_jul25,
           median(p.market_value_in_eur)                        AS median_value_eur,
           count(*) FILTER (WHERE p.market_value_in_eur <= 1000000) AS valued_1m_or_less
    FROM players p
    LEFT JOIN latest_valuation lv USING (player_id)
    WHERE p.current_club_domestic_competition_id IN ({leagues})
      AND TRY_CAST(p.last_season AS INTEGER) >= 2024
    GROUP BY 1
    ORDER BY 1
""").fetchall()

print(f"\n{'league':<6} {'players':>8} {'with value':>11} {'valued since Jul-25':>20} "
      f"{'median EUR':>12} {'<= EUR 1M':>10}")
for league, players, with_value, recent, median_value, cheap in rows:
    median_text = f"{median_value:,.0f}" if median_value is not None else "-"
    print(f"{league:<6} {players:>8} {with_value:>11} {recent:>20} {median_text:>12} {cheap:>10}")

con.close()
print("\nDone. Paste the output back to Claude.")
