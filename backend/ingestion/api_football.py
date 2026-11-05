"""API-Football importer.

Commands (inside the backend container):
    python -m ingestion.api_football fetch       # download + cache, up to ~80 requests per run
    python -m ingestion.api_football status      # what is cached, what is left (no requests)
    python -m ingestion.api_football map-clubs   # link API teams to Transfermarkt clubs (no requests)
    python -m ingestion.api_football load        # link players + store stats from the cache (no requests)
    python -m ingestion.api_football gap-fill    # fetch own records of regulars missing after `load`
    python -m ingestion.api_football enable-league --tm PO1 --af 94   # verify an id (1 request), then enable

`fetch` is resumable: run it once a day until `status` says all pages are cached.
The free plan only serves pages 1-3 of /players; teams with more pages are listed
by `status` so missing regulars can be fetched individually in the next step.
"""

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from rapidfuzz import fuzz
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models import Club, ClubSourceId, DataSource, ImportRun, League, PlayerSeasonStats
from ingestion.api_football_client import ApiFootballClient, BudgetExhausted
from ingestion.normalize import normalize_name

FREE_PLAN_MAX_PAGE = 3
OVERRIDES_FILE = Path(__file__).with_name("club_overrides.json")


def cache_dir() -> Path:
    return Path(get_settings().raw_dir) / "api_football"


def enabled_leagues(session: Session) -> list[League]:
    return session.scalars(
        select(League).where(League.enabled, League.apifootball_id.is_not(None)).order_by(League.id)
    ).all()


# =====================================================================
# fetch
# =====================================================================

@dataclass
class FetchProgress:
    teams_total: int = 0
    teams_complete: int = 0
    pages_cached: int = 0
    truncated: list | None = None


def fetch(client: ApiFootballClient, leagues: list[League], season: int) -> FetchProgress:
    """Fetch /teams per league, then /players pages 1-3 per team. Raises BudgetExhausted when it must stop."""
    progress = FetchProgress(truncated=[])
    teams = []
    for league in leagues:
        body = client.get("teams", {"league": league.apifootball_id, "season": season})
        for item in body.get("response") or []:
            teams.append((league, item["team"]["id"], item["team"]["name"]))
    progress.teams_total = len(teams)

    for league, team_id, team_name in teams:
        first = client.get("players", {"team": team_id, "season": season, "page": 1})
        total_pages = (first.get("paging") or {}).get("total") or 1
        progress.pages_cached += 1
        for page in range(2, min(total_pages, FREE_PLAN_MAX_PAGE) + 1):
            client.get("players", {"team": team_id, "season": season, "page": page})
            progress.pages_cached += 1
        progress.teams_complete += 1
        if total_pages > FREE_PLAN_MAX_PAGE:
            progress.truncated.append((league.name, team_name, total_pages))
    return progress


def cmd_fetch(args) -> None:
    settings = get_settings()
    client = ApiFootballClient(settings.api_football_key, cache_dir(), max_requests=args.max_requests)
    with SessionLocal() as session:
        source = session.scalar(select(DataSource).where(DataSource.code == "api_football"))
        run = ImportRun(source_id=source.id, kind="af_fetch", status="running", notes=f"season={args.season}")
        session.add(run)
        session.commit()
        leagues = enabled_leagues(session)
        print(f"Fetching season {args.season} for: {', '.join(lg.name for lg in leagues)}")
        print(f"Run cap: {args.max_requests} live requests (cached responses are free)\n")
        try:
            progress = fetch(client, leagues, args.season)
            run.status = "success"
            done = True
        except BudgetExhausted as exc:
            run.status = "partial"
            run.notes = f"season={args.season}; stopped: {exc}"
            done = False
            print(f"Stopped: {exc}")
        run.requests_used = client.live_requests
        run.finished_at = datetime.now(timezone.utc)
        session.commit()

    print(f"\nLive requests this run: {client.live_requests}; daily quota left: {client.daily_remaining}")
    if done:
        print(f"All pages cached: {progress.teams_complete}/{progress.teams_total} teams.")
    else:
        print("Not finished yet. Run the same command again tomorrow; it continues where it stopped.")
    print("Run `python -m ingestion.api_football status` for details.")


# =====================================================================
# status (offline)
# =====================================================================

def cmd_status(args) -> None:
    client = ApiFootballClient("offline", cache_dir())
    with SessionLocal() as session:
        leagues = enabled_leagues(session)
    teams_total = teams_done = pages = 0
    truncated, missing_leagues = [], []
    for league in leagues:
        body = client.cached("teams", {"league": league.apifootball_id, "season": args.season})
        if body is None:
            missing_leagues.append(league.name)
            continue
        for item in body.get("response") or []:
            teams_total += 1
            team_id, name = item["team"]["id"], item["team"]["name"]
            first = client.cached("players", {"team": team_id, "season": args.season, "page": 1})
            if first is None:
                continue
            total_pages = (first.get("paging") or {}).get("total") or 1
            needed = min(total_pages, FREE_PLAN_MAX_PAGE)
            have = sum(
                client.cached("players", {"team": team_id, "season": args.season, "page": p}) is not None
                for p in range(1, needed + 1)
            )
            pages += have
            if have == needed:
                teams_done += 1
            if total_pages > FREE_PLAN_MAX_PAGE:
                truncated.append(f"{league.name}: {name} ({total_pages} pages)")

    print(f"Season {args.season} cache status")
    if missing_leagues:
        print(f"  team lists not fetched yet: {', '.join(missing_leagues)}")
    print(f"  teams fully cached: {teams_done}/{teams_total}")
    print(f"  player pages cached: {pages}")
    print(f"  teams with more than {FREE_PLAN_MAX_PAGE} pages (need gap fill later): {len(truncated)}")
    for line in truncated:
        print(f"    {line}")


# =====================================================================
# map-clubs (offline)
# =====================================================================

# Words that carry no identity in club names ("Futbol Club Barcelona" -> "barcelona")
CLUB_STOPWORDS = {
    "fc", "cf", "afc", "ac", "as", "ss", "ssc", "us", "sc", "sv", "vfb", "vfl", "tsg", "rc", "ogc", "cd", "ud",
    "rcd", "sd", "ca", "club", "football", "futbol", "calcio", "associazione", "sportiva", "societa", "de", "del",
    "la", "le", "of", "the", "e", "v", "ev", "und", "fur", "verein", "ballspielverein", "sportgemeinschaft",
    "turn", "fussball", "spielbetriebs", "gmbh", "kgaa", "spa", "s", "p", "a", "sad", "cfc", "bewegungsspiele",
    "1", "fk", "deportivo", "balompie", "sportverein", "sociedad", "anonima", "srl",
}


def club_key(name: str) -> str:
    tokens = [t for t in normalize_name(name).split() if t not in CLUB_STOPWORDS and not t.isdigit()]
    return " ".join(tokens)


def club_similarity(api_name: str, tm_name: str, api_venue: str | None = None, tm_venue: str | None = None) -> float:
    score = fuzz.token_set_ratio(club_key(api_name), club_key(tm_name))
    if api_venue and tm_venue and fuzz.token_set_ratio(normalize_name(api_venue), normalize_name(tm_venue)) >= 90:
        score = max(score, 90.0)  # same stadium is strong supporting evidence
    return score


def match_clubs(api_teams: list[dict], tm_clubs: list[dict], threshold: float = 70) -> tuple[list, list]:
    """One-to-one greedy matching by best similarity.

    api_teams: [{"id", "name", "venue"}]; tm_clubs: [{"club_id", "name", "venue"}]
    Returns (matches [(api, tm, score)], unmatched_api [api]).
    """
    pairs = sorted(
        (
            (club_similarity(a["name"], t["name"], a.get("venue"), t.get("venue")), i, j)
            for i, a in enumerate(api_teams)
            for j, t in enumerate(tm_clubs)
        ),
        reverse=True,
    )
    used_api, used_tm, matches = set(), set(), []
    for score, i, j in pairs:
        if score < threshold:
            break
        if i in used_api or j in used_tm:
            continue
        used_api.add(i)
        used_tm.add(j)
        matches.append((api_teams[i], tm_clubs[j], score))
    unmatched = [a for i, a in enumerate(api_teams) if i not in used_api]
    return matches, unmatched


def _tm_venues(tm_ext_ids: list[str]) -> dict[str, str]:
    """Stadium names from the Transfermarkt snapshot, if available (optional evidence)."""
    path = Path(get_settings().tm_duckdb_path)
    if not path.exists() or not tm_ext_ids:
        return {}
    import duckdb

    con = duckdb.connect(str(path), read_only=True)
    try:
        cols = {r[0] for r in con.execute("DESCRIBE clubs").fetchall()}
        if "stadium_name" not in cols:
            return {}
        rows = con.execute(
            "SELECT CAST(club_id AS VARCHAR), stadium_name FROM clubs WHERE CAST(club_id AS VARCHAR) IN "
            "(SELECT unnest(?::VARCHAR[]))",
            [tm_ext_ids],
        ).fetchall()
        return {cid: name for cid, name in rows if name}
    finally:
        con.close()


def cmd_map_clubs(args) -> None:
    client = ApiFootballClient("offline", cache_dir())
    overrides = json.loads(OVERRIDES_FILE.read_text()) if OVERRIDES_FILE.exists() else {}
    with SessionLocal() as session:
        af = session.scalar(select(DataSource).where(DataSource.code == "api_football"))
        tm = session.scalar(select(DataSource).where(DataSource.code == "transfermarkt"))
        total_matched = 0
        review, unmatched_all = [], []
        for league in enabled_leagues(session):
            body = client.cached("teams", {"league": league.apifootball_id, "season": args.season})
            if body is None:
                print(f"{league.name}: team list not cached yet - run `fetch` first")
                continue
            api_teams = [
                {"id": it["team"]["id"], "name": it["team"]["name"], "venue": (it.get("venue") or {}).get("name")}
                for it in body.get("response") or []
            ]
            # Transfermarkt clubs that played in this league in this season
            rows = session.execute(
                select(Club.id, Club.name, ClubSourceId.external_id)
                .join(ClubSourceId, (ClubSourceId.club_id == Club.id) & (ClubSourceId.source_id == tm.id))
                .where(
                    Club.id.in_(
                        select(PlayerSeasonStats.club_id).where(
                            PlayerSeasonStats.league_id == league.id,
                            PlayerSeasonStats.season == args.season,
                            PlayerSeasonStats.source_id == tm.id,
                        )
                    )
                )
            ).all()
            venues = _tm_venues([r.external_id for r in rows])
            tm_clubs = [{"club_id": r.id, "name": r.name, "tm_id": r.external_id, "venue": venues.get(r.external_id)}
                        for r in rows]

            # manual overrides first: {"<api team id>": "<transfermarkt club id>"}
            forced = []
            for a in list(api_teams):
                tm_ext = overrides.get(str(a["id"]))
                t = next((c for c in tm_clubs if c["tm_id"] == str(tm_ext)), None) if tm_ext else None
                if t:
                    forced.append((a, t, 100.0))
                    api_teams.remove(a)
                    tm_clubs.remove(t)
            matches, unmatched = match_clubs(api_teams, tm_clubs)
            matches = forced + matches

            for a, t, score in matches:
                link = session.get(ClubSourceId, (af.id, str(a["id"])))
                if link:
                    link.club_id = t["club_id"]
                else:
                    session.add(ClubSourceId(source_id=af.id, external_id=str(a["id"]), club_id=t["club_id"]))
                if score < 90:
                    review.append(f"{league.name}: '{a['name']}' -> '{t['name']}' (score {score:.0f})")
            unmatched_all += [f"{league.name}: '{a['name']}' (API id {a['id']})" for a in unmatched]
            total_matched += len(matches)
            print(f"{league.name}: {len(matches)}/{len(matches) + len(unmatched)} teams matched")
        session.commit()

    print(f"\nTotal matched: {total_matched}")
    if review:
        print("\nPlease check these lower-confidence matches:")
        print("\n".join(f"  {line}" for line in review))
    if unmatched_all:
        print("\nNot matched (add to ingestion/club_overrides.json as {\"<API id>\": \"<Transfermarkt club id>\"}):")
        print("\n".join(f"  {line}" for line in unmatched_all))


def cmd_load(args) -> None:
    from ingestion.af_load import load_cached

    client = ApiFootballClient("offline", cache_dir())
    with SessionLocal() as session:
        try:
            report = load_cached(session, client, enabled_leagues(session), args.season)
            session.commit()
        except BaseException:
            session.rollback()
            raise
    report.print()


# =====================================================================
# gap-fill
# =====================================================================

GAP_MIN_MINUTES = 450  # only players with at least 5 full league matches are worth a request


def search_token(full_name: str) -> str | None:
    """Longest name part (API search needs >= 4 characters), e.g. 'Kaoru Mitoma' -> 'mitoma'."""
    parts = sorted((p for p in normalize_name(full_name).split() if len(p) >= 4), key=len, reverse=True)
    return parts[0] if parts else None


def gap_fill_targets(
    session: Session, leagues: list[League], season: int, min_minutes: int = GAP_MIN_MINUTES, only_linked: bool = False
):
    """Transfermarkt regulars with no stored API-Football line for that league and season, most minutes first.

    only_linked: keep only players whose API-Football id is already known (one cheap request each,
    and safe to run while the main fetch is still in progress).
    """
    from sqlalchemy import func

    from app.models import Player, PlayerSourceId

    af = session.scalar(select(DataSource).where(DataSource.code == "api_football"))
    tm = session.scalar(select(DataSource).where(DataSource.code == "transfermarkt"))
    league_ids = [lg.id for lg in leagues]
    tm_minutes = (
        select(PlayerSeasonStats.player_id, PlayerSeasonStats.league_id, func.sum(PlayerSeasonStats.minutes).label("minutes"))
        .where(PlayerSeasonStats.source_id == tm.id, PlayerSeasonStats.season == season,
               PlayerSeasonStats.league_id.in_(league_ids))
        .group_by(PlayerSeasonStats.player_id, PlayerSeasonStats.league_id)
        .subquery()
    )
    has_af = (
        select(PlayerSeasonStats.id)
        .where(PlayerSeasonStats.source_id == af.id, PlayerSeasonStats.season == season,
               PlayerSeasonStats.player_id == tm_minutes.c.player_id,
               PlayerSeasonStats.league_id == tm_minutes.c.league_id)
        .exists()
    )
    af_link = (
        select(PlayerSourceId.external_id)
        .where(PlayerSourceId.source_id == af.id, PlayerSourceId.player_id == tm_minutes.c.player_id)
        .scalar_subquery()
    )
    rows = session.execute(
        select(Player.full_name, tm_minutes.c.league_id, tm_minutes.c.minutes, af_link.label("af_id"))
        .join(Player, Player.id == tm_minutes.c.player_id)
        .where(tm_minutes.c.minutes >= min_minutes, ~has_af)
        .order_by(tm_minutes.c.minutes.desc())
    ).all()
    league_af = {lg.id: lg.apifootball_id for lg in leagues}
    return [(r.full_name, league_af[r.league_id], r.minutes, r.af_id) for r in rows if r.af_id or not only_linked]


def cmd_gap_fill(args) -> None:
    settings = get_settings()
    client = ApiFootballClient(settings.api_football_key, cache_dir(), max_requests=args.max_requests)
    with SessionLocal() as session:
        targets = gap_fill_targets(session, enabled_leagues(session), args.season, args.min_minutes, args.only_linked)
    scope = " (known API id only)" if args.only_linked else ""
    print(f"Regulars (>= {args.min_minutes} league minutes) without a reconciled API-Football line{scope}: {len(targets)}")
    by_id = by_search = already = skipped = 0
    try:
        for name, league_af_id, minutes, af_id in targets:
            if af_id:
                params = {"id": int(af_id), "season": args.season}
            else:
                token = search_token(name)
                if token is None:
                    skipped += 1
                    continue
                params = {"league": league_af_id, "search": token, "season": args.season}
            if client.cached("players", params) is not None:
                already += 1  # fetched before; if still missing, it needs manual review
                continue
            client.get("players", params)
            by_id += "id" in params
            by_search += "search" in params
        finished = True
    except BudgetExhausted as exc:
        finished = False
        print(f"Stopped: {exc}")
    print(f"Fetched now: {by_id} by API id, {by_search} by name search; already cached: {already}; "
          f"skipped (name too short): {skipped}")
    print(f"Live requests: {client.live_requests}; daily quota left: {client.daily_remaining}")
    print("Now run `python -m ingestion.api_football load` to use the new records."
          + ("" if finished else " Then run gap-fill again tomorrow for the rest."))


# =====================================================================
# enable-league
# =====================================================================

COUNTRY_ALIASES = {"turkiye": "turkey", "czechia": "czech republic", "north macedonia": "macedonia"}


def _country_key(name: str | None) -> str:
    key = normalize_name(name)
    return COUNTRY_ALIASES.get(key, key)


def check_league_response(body: dict, league: League, season: int) -> tuple[list[str], dict]:
    """Compare an API-Football /leagues response with our league row. Returns (problems, info)."""
    items = body.get("response") or []
    if not items:
        return ["API-Football returned no league for this id and season"], {}
    item = items[0]
    info = {
        "name": (item.get("league") or {}).get("name"),
        "type": (item.get("league") or {}).get("type"),
        "country": (item.get("country") or {}).get("name"),
    }
    problems = []
    if _country_key(info["country"]) != _country_key(league.country):
        problems.append(f"country is '{info['country']}', expected '{league.country}'")
    if info["type"] and info["type"].lower() != "league":
        problems.append(f"competition type is '{info['type']}', not a league")
    season_row = next((s for s in item.get("seasons") or [] if s.get("year") == season), None)
    if season_row is None:
        problems.append(f"season {season} not listed")
    else:
        cov = season_row.get("coverage") or {}
        info["players"] = cov.get("players")
        info["statistics_players"] = (cov.get("fixtures") or {}).get("statistics_players")
        if not cov.get("players"):
            problems.append(f"no player coverage for season {season}")
    return problems, info


def cmd_enable_league(args) -> None:
    settings = get_settings()
    client = ApiFootballClient(settings.api_football_key, cache_dir(), max_requests=3)
    with SessionLocal() as session:
        league = session.scalar(select(League).where(League.tm_competition_id == args.tm))
        if league is None:
            sys.exit(f"No league with Transfermarkt code {args.tm}")
        clash = session.scalar(select(League).where(League.apifootball_id == args.af, League.id != league.id))
        if clash is not None:
            sys.exit(f"API-Football id {args.af} is already used by {clash.name}")
        body = client.get("leagues", {"id": args.af, "season": args.season})
        problems, info = check_league_response(body, league, args.season)
        print(f"{league.name} ({league.country}, {args.tm}) vs API-Football id {args.af}: "
              f"'{info.get('name')}', {info.get('country')}, players={info.get('players')}, "
              f"statistics_players={info.get('statistics_players')}")
        if problems:
            sys.exit("Not enabled: " + "; ".join(problems))
        league.apifootball_id = args.af
        league.enabled = True
        session.commit()
    print(f"Enabled. Next: `python -m ingestion.transfermarkt` to load its players and values, "
          f"then `fetch` continues with its teams after the leagues already in progress.")


def main() -> None:
    parser = argparse.ArgumentParser(description="API-Football importer")
    sub = parser.add_subparsers(dest="command", required=True)
    p_fetch = sub.add_parser("fetch", help="download and cache (uses requests)")
    p_fetch.add_argument("--season", type=int, default=2024)
    p_fetch.add_argument("--max-requests", type=int, default=80)
    p_status = sub.add_parser("status", help="show cache progress (no requests)")
    p_status.add_argument("--season", type=int, default=2024)
    p_map = sub.add_parser("map-clubs", help="link API teams to Transfermarkt clubs (no requests)")
    p_map.add_argument("--season", type=int, default=2024)
    p_load = sub.add_parser("load", help="link players and store stats from the cache (no requests)")
    p_load.add_argument("--season", type=int, default=2024)
    p_gap = sub.add_parser("gap-fill", help="fetch own records of regulars still missing after load (uses requests)")
    p_gap.add_argument("--season", type=int, default=2024)
    p_gap.add_argument("--max-requests", type=int, default=80)
    p_gap.add_argument("--min-minutes", type=int, default=GAP_MIN_MINUTES)
    p_gap.add_argument("--only-linked", action="store_true",
                       help="only players whose API-Football id is known (safe while fetch is unfinished)")
    p_en = sub.add_parser("enable-league", help="verify a league's API-Football id (1 request) and enable it")
    p_en.add_argument("--tm", required=True, help="Transfermarkt competition code, e.g. PO1")
    p_en.add_argument("--af", required=True, type=int, help="API-Football league id to verify")
    p_en.add_argument("--season", type=int, default=2024)
    args = parser.parse_args()
    {"fetch": cmd_fetch, "status": cmd_status, "map-clubs": cmd_map_clubs, "load": cmd_load,
     "gap-fill": cmd_gap_fill, "enable-league": cmd_enable_league}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
