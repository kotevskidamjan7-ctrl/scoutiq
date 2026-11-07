"""Load UEFA association coefficients as league strength (alternative to ClubElo).

    python -m ingestion.uefa_coefficients

The league-strength adjustment needs one strength number per league and season. ClubElo (mean club
rating) is the first choice; when it is unavailable, UEFA's season points per association measure the
same thing from European results. Values come from ingestion/reference/uefa_country_coefficients.csv, which
lists its sources. Stored with method 'uefa_season_points', dated at the end of each season.
"""

import csv
from datetime import date
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models import League, LeagueStrength

METHOD = "uefa_season_points"
DATA = Path(__file__).resolve().parent / "reference" / "uefa_country_coefficients.csv"


def read(path: Path = DATA) -> list[dict]:
    with path.open(encoding="utf-8") as fh:
        lines = [line for line in fh if not line.startswith("#")]
    rows = []
    for r in csv.DictReader(lines):
        season, points = int(r["season"]), float(r["points"])
        if not 0 <= points <= 60:
            raise ValueError(f"implausible UEFA points {points} for {r['tm_code']} {season}")
        rows.append({"tm_code": r["tm_code"].strip(), "season": season, "points": points})
    return rows


def load(session: Session, rows: list[dict]) -> int:
    leagues = {lg.tm_competition_id: lg.id for lg in session.scalars(select(League).where(League.tm_competition_id.is_not(None)))}
    session.execute(delete(LeagueStrength).where(LeagueStrength.method == METHOD))
    n = 0
    for r in rows:
        lid = leagues.get(r["tm_code"])
        if lid is None:
            continue
        # end of the season, inside the August-June window the adjustment reads for that season
        session.add(LeagueStrength(league_id=lid, as_of_date=date(r["season"] + 1, 5, 31),
                                   mean_club_elo=r["points"], method=METHOD))
        n += 1
    session.flush()
    return n


def main() -> None:
    rows = read()
    with SessionLocal() as session:
        n = load(session, rows)
        session.commit()
        names = dict(session.execute(select(League.tm_competition_id, League.name)).all())
    print(f"UEFA association coefficients loaded: {n} league-seasons (method '{METHOD}')")
    for code in sorted({r["tm_code"] for r in rows}, key=lambda c: -max(r["points"] for r in rows if r["tm_code"] == c)):
        pts = {r["season"]: r["points"] for r in rows if r["tm_code"] == code}
        print(f"  {names.get(code, code):<24} 2024/25 {pts.get(2024, float('nan')):6.3f}   2025/26 {pts.get(2025, float('nan')):6.3f}")
    print("Next: python -m app.scoring.league_adjust --strength uefa")


if __name__ == "__main__":
    main()
