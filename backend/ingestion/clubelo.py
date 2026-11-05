"""ClubElo loader: league strength = mean Elo of a country's top-division clubs.

ClubElo (clubelo.com) rates clubs from match results, including European games,
so all leagues sit on one scale. Its free CSV API returns every rated club on a date:
    http://api.clubelo.com/YYYY-MM-DD   ->  Rank,Club,Country,Level,Elo,From,To

For each season we sample the 1st of each month from September to May (9 dates)
and store, per league and date, the mean Elo of clubs with that country and Level 1.
Responses are cached in RAW_DIR/clubelo/, so each date is downloaded once.

Usage (inside the backend container):
    python -m ingestion.clubelo                  # seasons 2024 and 2025
    python -m ingestion.clubelo --seasons 2024
"""

import argparse
import io
import time
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import pandas as pd
import requests
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models import League, LeagueStrength

BASE_URL = "http://api.clubelo.com"
METHOD = "mean_club_elo_level1"

# Transfermarkt competition code -> ClubElo country code. The top 5 are verified by the
# loader's club counts; the others are checked when their league is enabled (counts reported).
CLUBELO_COUNTRY = {
    "GB1": "ENG", "ES1": "ESP", "IT1": "ITA", "L1": "GER", "FR1": "FRA",
    "PO1": "POR", "NL1": "NED", "BE1": "BEL", "TR1": "TUR",
    "A1": "AUT", "C1": "SUI", "PL1": "POL", "KR1": "CRO", "SER1": "SRB",
}


def season_dates(season: int) -> list[date]:
    """1st of September (season) to 1st of May (season + 1)."""
    months = [(season, m) for m in range(9, 13)] + [(season + 1, m) for m in range(1, 6)]
    return [date(y, m, 1) for y, m in months]


def parse_csv(text: str) -> pd.DataFrame:
    """Normalise ClubElo's CSV to columns club, country, level, elo. Fails loudly on a different layout."""
    df = pd.read_csv(io.StringIO(text))
    df.columns = [c.strip().lower() for c in df.columns]
    if "team" in df.columns and "club" not in df.columns:
        df = df.rename(columns={"team": "club"})
    missing = {"club", "country", "level", "elo"} - set(df.columns)
    if missing:
        raise SystemExit(f"ClubElo CSV layout not as expected: missing {sorted(missing)}; got {list(df.columns)}")
    df["level"] = pd.to_numeric(df["level"], errors="coerce")
    df["elo"] = pd.to_numeric(df["elo"], errors="coerce")
    return df[["club", "country", "level", "elo"]].dropna(subset=["elo"])


def league_means(df: pd.DataFrame, country: str) -> tuple[float | None, int]:
    top = df[(df["country"] == country) & (df["level"] == 1)]
    return (float(top["elo"].mean()) if len(top) else None), len(top)


class ClubEloUnavailable(Exception):
    """ClubElo did not answer after all retries (its server, not ours)."""


RETRY_WAITS = (5, 15, 45)  # seconds between attempts after a server error or timeout


class ClubEloClient:
    def __init__(self, cache_dir: Path, session: requests.Session | None = None, sleep=time.sleep):
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.session = session or requests.Session()
        self.sleep = sleep
        self.live_requests = 0

    def on(self, day: date) -> pd.DataFrame:
        path = self.cache_dir / f"{day.isoformat()}.csv"
        if not path.exists():
            if self.live_requests:
                self.sleep(1.0)  # be polite to a free service
            path.write_text(self._download(day), encoding="utf-8")
        return parse_csv(path.read_text(encoding="utf-8"))

    def _download(self, day: date) -> str:
        url = f"{BASE_URL}/{day.isoformat()}"
        last_error = ""
        for attempt, wait in enumerate((0, *RETRY_WAITS)):
            if wait:
                print(f"  ClubElo did not answer ({last_error}); retrying in {wait} s ...")
                self.sleep(wait)
            try:
                resp = self.session.get(url, timeout=30)
            except requests.RequestException as exc:
                last_error = exc.__class__.__name__
                continue
            if resp.status_code >= 500:
                last_error = f"HTTP {resp.status_code}"
                continue
            resp.raise_for_status()  # 4xx: a real problem with the request, do not retry
            self.live_requests += 1
            return resp.text
        raise ClubEloUnavailable(f"{url} failed after {len(RETRY_WAITS) + 1} attempts ({last_error})")


@dataclass
class EloReport:
    dates: int = 0
    downloaded: int = 0
    rows: int = 0
    clubs_per_league: dict = field(default_factory=dict)  # league -> (min, max) clubs found per date
    season_means: dict = field(default_factory=dict)      # (league, season) -> mean Elo

    def print(self) -> None:
        print("\nClubElo league strength")
        print(f"  dates: {self.dates} (downloaded now: {self.downloaded}); rows stored: {self.rows}")
        print("  league: clubs found per date (min-max); mean Elo per season")
        for league, (lo, hi) in sorted(self.clubs_per_league.items()):
            means = ", ".join(f"{s}/{str(s + 1)[2:]}: {e:.0f}" for (lg, s), e in sorted(self.season_means.items())
                              if lg == league)
            warn = "   <- no clubs found: check the country code" if hi == 0 else ""
            print(f"    {league:<24} {lo}-{hi} clubs; {means}{warn}")


def load(session: Session, client: ClubEloClient, seasons: list[int]) -> EloReport:
    report = EloReport()
    leagues = session.scalars(select(League).where(League.tm_competition_id.in_(list(CLUBELO_COUNTRY)))).all()
    rows = []
    for season in seasons:
        per_league: dict[str, list[float]] = {}
        for day in season_dates(season):
            before = client.live_requests
            df = client.on(day)
            report.dates += 1
            report.downloaded += client.live_requests - before
            for lg in leagues:
                mean, n = league_means(df, CLUBELO_COUNTRY[lg.tm_competition_id])
                lo, hi = report.clubs_per_league.get(lg.name, (n, n))
                report.clubs_per_league[lg.name] = (min(lo, n), max(hi, n))
                if mean is not None:
                    rows.append({"league_id": lg.id, "as_of_date": day, "mean_club_elo": round(mean, 2), "method": METHOD})
                    per_league.setdefault(lg.name, []).append(mean)
        for name, values in per_league.items():
            report.season_means[(name, season)] = sum(values) / len(values)
    if rows:
        stmt = pg_insert(LeagueStrength).values(rows)
        stmt = stmt.on_conflict_do_update(index_elements=["league_id", "as_of_date", "method"],
                                          set_={"mean_club_elo": stmt.excluded.mean_club_elo})
        session.execute(stmt)
    report.rows = len(rows)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Load ClubElo league strength")
    parser.add_argument("--seasons", type=int, nargs="+", default=[2024, 2025])
    args = parser.parse_args()
    client = ClubEloClient(Path(get_settings().raw_dir) / "clubelo")
    with SessionLocal() as session:
        try:
            report = load(session, client, args.seasons)
            session.commit()
        except ClubEloUnavailable as exc:
            session.rollback()
            raise SystemExit(
                f"\nClubElo is not responding right now: {exc}\n"
                "This is a problem on clubelo.com's side. Dates already downloaded are cached;\n"
                "run the same command again later and it continues where it stopped."
            ) from None
        except BaseException:
            session.rollback()
            raise
    report.print()


if __name__ == "__main__":
    main()
