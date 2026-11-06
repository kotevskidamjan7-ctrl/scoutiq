"""Load cached API-Football player pages into PostgreSQL (no API requests).

For every cached /players page of the enabled leagues:
  1. Parse each player's DOMESTIC-LEAGUE stat entry only (cups and Europe are ignored).
  2. Link the API-Football player to the canonical (Transfermarkt) player:
       a. already linked earlier                    -> reuse
       b. same birth date + name similarity >= 85   -> 'dob_name'
       c. otherwise left for manual review in `link_candidate` (never guessed)
  3. Reconcile: a line is stored only if its league minutes agree with Transfermarkt's
     season total for that player and league. In team listings the API relabels every
     line with the queried team and mixes partial and full seasons (Rashford: only his
     United part; Cunha: his whole Wolves season shown under United), so lines that do
     not reconcile are HELD and repaired by `gap-fill`, which fetches the player's own
     record (one line per real club, summed here).
  4. Attribute the stats to the club with most Transfermarkt league minutes that season.
  5. Store as source 'api_football'. Lines with stats but no minutes are rejected.

Verified quirks of the real API response (2026-11-04, team 33, season 2024):
  * height is "180" or "178 cm"          -> digits parsed, out-of-range -> NULL
  * games.rating is a string             -> float
  * passes.accuracy is not a percentage  -> stored as reported, not used for scoring
  * counting stats are often null for 0  -> kept NULL here; Phase 4 decides per league

Usage:  python -m ingestion.api_football load
"""

import re
from collections import defaultdict
from pathlib import Path
from dataclasses import dataclass, field
from datetime import date, datetime, timezone

from rapidfuzz import fuzz
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models import (
    DataSource,
    ImportRun,
    League,
    LinkCandidate,
    Player,
    PlayerSeasonStats,
    PlayerSourceId,
)
from ingestion.api_football_client import ApiFootballClient
from ingestion.normalize import normalize_name
from ingestion.batching import chunks

NAME_THRESHOLD = 85          # same birth date, name alone
LEAGUE_NAME_THRESHOLD = 60   # same birth date AND the player has Transfermarkt minutes in this league-season
MINUTES_REL_TOL = 0.15       # API vs Transfermarkt league minutes must agree within 15% ...
MINUTES_ABS_TOL = 90         # ... or within 90 minutes (one match), whichever is looser


# ---------- parsing ----------

def to_int(value) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def to_float(value) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def parse_height(value) -> int | None:
    """'180' or '178 cm' -> 180 / 178; implausible values -> None."""
    match = re.search(r"\d+", str(value or ""))
    height = int(match.group()) if match else None
    return height if height and 150 <= height <= 215 else None


def parse_date(value) -> date | None:
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


@dataclass
class AfEntry:
    """One player's domestic-league season line from API-Football."""

    af_player_id: int
    name: str
    full_name: str
    lastname: str
    birth_date: date | None
    height_cm: int | None
    league_af_id: int
    listed_team_id: int
    stats: dict
    origin: str = "team"  # "team" = from a team listing, "player" = from the player's own record


STAT_FIELDS = {
    # our column: (API group, API field, parser)
    "position_reported": ("games", "position", lambda v: v),
    "appearances": ("games", "appearences", to_int),  # sic: API spelling
    "lineups": ("games", "lineups", to_int),
    "minutes": ("games", "minutes", to_int),
    "rating": ("games", "rating", to_float),
    "goals": ("goals", "total", to_int),
    "assists": ("goals", "assists", to_int),
    "goals_conceded": ("goals", "conceded", to_int),
    "saves": ("goals", "saves", to_int),
    "shots_total": ("shots", "total", to_int),
    "shots_on": ("shots", "on", to_int),
    "passes_total": ("passes", "total", to_int),
    "passes_key": ("passes", "key", to_int),
    "pass_accuracy": ("passes", "accuracy", to_float),
    "tackles": ("tackles", "total", to_int),
    "blocks": ("tackles", "blocks", to_int),
    "interceptions": ("tackles", "interceptions", to_int),
    "duels_total": ("duels", "total", to_int),
    "duels_won": ("duels", "won", to_int),
    "dribbles_attempts": ("dribbles", "attempts", to_int),
    "dribbles_success": ("dribbles", "success", to_int),
    "dribbled_past": ("dribbles", "past", to_int),
    "fouls_drawn": ("fouls", "drawn", to_int),
    "fouls_committed": ("fouls", "committed", to_int),
    "cards_yellow": ("cards", "yellow", to_int),
    "cards_yellowred": ("cards", "yellowred", to_int),
    "cards_red": ("cards", "red", to_int),
    "penalty_won": ("penalty", "won", to_int),
    "penalty_committed": ("penalty", "commited", to_int),  # sic: API spelling
    "penalty_scored": ("penalty", "scored", to_int),
    "penalty_missed": ("penalty", "missed", to_int),
    "penalty_saved": ("penalty", "saved", to_int),
}

ACTIVITY_FIELDS = ("shots_total", "passes_total", "passes_key", "duels_total", "tackles", "saves")


def parse_page(body: dict, league_af_id: int) -> list[AfEntry]:
    entries = []
    for item in body.get("response") or []:
        p = item.get("player") or {}
        for st in item.get("statistics") or []:
            if (st.get("league") or {}).get("id") != league_af_id:
                continue  # cups, Europe, Community Shield...
            stats = {col: parser((st.get(group) or {}).get(fld)) for col, (group, fld, parser) in STAT_FIELDS.items()}
            entries.append(
                AfEntry(
                    af_player_id=p["id"],
                    name=p.get("name") or "",
                    full_name=f"{p.get('firstname') or ''} {p.get('lastname') or ''}".strip() or p.get("name") or "",
                    lastname=p.get("lastname") or "",
                    birth_date=parse_date((p.get("birth") or {}).get("date")),
                    height_cm=parse_height(p.get("height")),
                    league_af_id=league_af_id,
                    listed_team_id=(st.get("team") or {}).get("id"),
                    stats=stats,
                )
            )
    return entries


def is_inconsistent(stats: dict) -> bool:
    """Activity recorded but no minutes played - cannot be turned into per-90 values."""
    return not stats.get("minutes") and any(stats.get(f) for f in ACTIVITY_FIELDS)


SUMMABLE = [c for c in STAT_FIELDS if c not in ("position_reported", "rating", "pass_accuracy")]


def combine(lines: list[AfEntry]) -> AfEntry:
    """Sum one player's league lines from different clubs into a season total."""
    if len(lines) == 1:
        return lines[0]
    base = lines[0]
    stats = {}
    for col in SUMMABLE:
        values = [ln.stats[col] for ln in lines if ln.stats[col] is not None]
        stats[col] = sum(values) if values else None
    weighted = [(ln.stats["rating"], ln.stats["minutes"] or 0) for ln in lines if ln.stats["rating"] is not None]
    total = sum(m for _, m in weighted)
    stats["rating"] = round(sum(r * m for r, m in weighted) / total, 6) if total else None
    stats["position_reported"] = base.stats["position_reported"]
    stats["pass_accuracy"] = None  # per-club values cannot be combined meaningfully
    return AfEntry(**{**base.__dict__, "stats": stats})


def minutes_agree(api_minutes: int, tm_minutes: int) -> bool:
    diff = abs(api_minutes - tm_minutes)
    return diff <= MINUTES_ABS_TOL or diff <= MINUTES_REL_TOL * max(api_minutes, tm_minutes)


# ---------- linking ----------

def name_score(entry: AfEntry, tm_name_normalized: str) -> float:
    candidates = [normalize_name(entry.full_name), normalize_name(entry.name)]
    score = max(fuzz.token_set_ratio(c, tm_name_normalized) for c in candidates if c)
    last = normalize_name(entry.lastname)
    if last and all(tok in tm_name_normalized.split() for tok in last.split()):
        score = max(score, 90.0)  # full surname present, e.g. 'Onana Onana' vs 'André Onana'
    return score


def best_dob_match(
    entry: AfEntry, same_dob: list[tuple[int, str]], in_league: set[int] | None = None
) -> tuple[int | None, float, str, int | None]:
    """Return (player_id, score, method_or_reason, best_candidate_id). Ambiguous or weak -> player_id None.

    in_league: Transfermarkt players with minutes in this league and season. A shared birth
    date plus a shared league-season is strong evidence, so a looser name match is accepted
    (nicknames such as 'Savinho' for 'Sávio Moreira de Oliveira').
    """
    scored = sorted(((name_score(entry, nm), pid) for pid, nm in same_dob), reverse=True)
    if not scored:
        return None, 0.0, "no player with this birth date", None
    best, pid = scored[0]
    if len(scored) > 1 and scored[1][0] >= best - 5 and best >= LEAGUE_NAME_THRESHOLD:
        return None, best, "two players with same birth date and similar names", pid
    if best >= NAME_THRESHOLD:
        return pid, best, "dob_name", pid
    if in_league is not None and pid in in_league and best >= LEAGUE_NAME_THRESHOLD:
        return pid, best, "dob_league_name", pid
    return None, best, "birth date matches but name differs", pid


# ---------- load ----------

@dataclass
class AfLoadReport:
    entries: int = 0
    duplicates_merged: int = 0
    from_player_records: int = 0
    linked_existing: int = 0
    linked_new: int = 0
    linked_by_method: dict = field(default_factory=dict)
    to_review: int = 0
    no_tm_minutes: int = 0
    inconsistent: int = 0
    held: list = field(default_factory=list)
    stored: int = 0
    per_league: dict = field(default_factory=dict)

    def print(self) -> None:
        print("\nAPI-Football load summary")
        print(f"  league entries parsed:          {self.entries}  (duplicates merged: {self.duplicates_merged}, "
              f"from player records: {self.from_player_records})")
        methods = ", ".join(f"{k}: {v}" for k, v in sorted(self.linked_by_method.items()))
        print(f"  linked (earlier / new):         {self.linked_existing} / {self.linked_new}  ({methods})")
        print(f"  sent to manual review:          {self.to_review}")
        print(f"  no Transfermarkt league minutes: {self.no_tm_minutes}")
        print(f"  rejected (stats, no minutes):   {self.inconsistent}")
        print(f"  held, minutes do not reconcile: {len(self.held)}  (repaired by gap-fill)")
        for line in self.held[:8]:
            print(f"    {line}")
        print(f"  stat rows stored:               {self.stored}")
        print("  per league: stored / with >= 900 minutes")
        for name, (stored, regulars) in sorted(self.per_league.items()):
            print(f"    {name:<16} {stored:>5} / {regulars}")


def _player_record_files(client: ApiFootballClient, season: int) -> list[Path]:
    """Cached gap-fill responses: /players?id=..&season=.. and /players?league=..&search=..&season=.."""
    return sorted(client.cache_dir.glob(f"players__id-*_season-{season}.json")) + sorted(
        client.cache_dir.glob(f"players__league-*_search-*_season-{season}.json")
    )


def collect_entries(client: ApiFootballClient, leagues: list[League], season: int, report: AfLoadReport) -> dict:
    """One entry per (API player, league). A player's own record beats team listings."""
    import json

    entries: dict[tuple[int, int], AfEntry] = {}
    for league in leagues:
        teams = client.cached("teams", {"league": league.apifootball_id, "season": season}) or {}
        for item in teams.get("response") or []:
            for page in (1, 2, 3):
                body = client.cached("players", {"team": item["team"]["id"], "season": season, "page": page})
                if body is None:
                    continue
                for e in parse_page(body, league.apifootball_id):
                    key = (e.af_player_id, e.league_af_id)
                    if key in entries:
                        report.duplicates_merged += 1
                        if (e.stats["minutes"] or 0) <= (entries[key].stats["minutes"] or 0):
                            continue
                    entries[key] = e

    # player records: one line per real club -> summed into a season total
    for path in _player_record_files(client, season):
        body = json.loads(path.read_text(encoding="utf-8"))["body"]
        for league in leagues:
            grouped: dict[int, dict[int, AfEntry]] = defaultdict(dict)
            for e in parse_page(body, league.apifootball_id):
                grouped[e.af_player_id][e.listed_team_id] = e  # one line per club
            for af_id, by_team in grouped.items():
                total = combine(list(by_team.values()))
                total.origin = "player"
                entries[(af_id, league.apifootball_id)] = total
                report.from_player_records += 1
    report.entries = len(entries)
    return entries


def load_cached(session: Session, client: ApiFootballClient, leagues: list[League], season: int) -> AfLoadReport:
    """Rebuild this season's API-Football stats from the cache (deterministic and repeatable)."""
    report = AfLoadReport()
    af = session.scalar(select(DataSource).where(DataSource.code == "api_football"))
    tm = session.scalar(select(DataSource).where(DataSource.code == "transfermarkt"))
    run = ImportRun(source_id=af.id, kind="af_load", status="running", notes=f"season={season}")
    session.add(run)
    session.flush()

    entries = collect_entries(client, leagues, season, report)
    league_by_af = {lg.apifootball_id: lg for lg in leagues}

    # --- reference data ---
    existing_links = dict(
        session.execute(select(PlayerSourceId.external_id, PlayerSourceId.player_id).where(PlayerSourceId.source_id == af.id)).all()
    )
    linked_players = set(existing_links.values())
    by_dob: dict[date, list[tuple[int, str]]] = defaultdict(list)
    for pid, nm, dob in session.execute(select(Player.id, Player.name_normalized, Player.birth_date)).all():
        if dob:
            by_dob[dob].append((pid, nm))

    # Transfermarkt per (player, league): total league minutes and the club with most minutes
    tm_total: dict[tuple[int, int], int] = defaultdict(int)
    tm_main: dict[tuple[int, int], tuple[int, int]] = {}
    for pid, club_id, league_id, minutes in session.execute(
        select(PlayerSeasonStats.player_id, PlayerSeasonStats.club_id, PlayerSeasonStats.league_id, PlayerSeasonStats.minutes)
        .where(PlayerSeasonStats.source_id == tm.id, PlayerSeasonStats.season == season)
    ).all():
        key = (pid, league_id)
        tm_total[key] += minutes or 0
        if key not in tm_main or (minutes or 0) > tm_main[key][1]:
            tm_main[key] = (club_id, minutes or 0)
    in_league: dict[int, set[int]] = defaultdict(set)
    for (pid, league_id), minutes in tm_total.items():
        if minutes > 0:
            in_league[league_id].add(pid)

    # rebuild: review queue and this season's API-Football stats are recomputed from the cache
    session.execute(delete(LinkCandidate).where(LinkCandidate.source_id == af.id, LinkCandidate.status == "pending"))
    session.execute(
        delete(PlayerSeasonStats).where(
            PlayerSeasonStats.source_id == af.id,
            PlayerSeasonStats.season == season,
            PlayerSeasonStats.league_id.in_([lg.id for lg in leagues]),
        )
    )
    reviewed = {ext for ext, in session.execute(
        select(LinkCandidate.external_id).where(LinkCandidate.source_id == af.id)
    )}  # accepted/rejected decisions are kept

    rows, queued = [], set()
    for (af_id, league_af_id), e in entries.items():
        league = league_by_af[league_af_id]
        ext = str(af_id)

        # 1. link
        player_id = existing_links.get(ext)
        if player_id:
            report.linked_existing += 1
        else:
            if e.birth_date:
                candidate, score, how, best_id = best_dob_match(e, by_dob.get(e.birth_date, []), in_league[league.id])
            else:
                candidate, score, how, best_id = None, 0.0, "no birth date", None
            if candidate and candidate in linked_players:
                candidate, how = None, "player already linked to another API-Football id"
            if candidate:
                session.add(PlayerSourceId(source_id=af.id, external_id=ext, player_id=candidate,
                                           match_method=how, match_confidence=round(score / 100, 3)))
                existing_links[ext] = candidate
                linked_players.add(candidate)
                player_id = candidate
                report.linked_new += 1
                report.linked_by_method[how] = report.linked_by_method.get(how, 0) + 1
            else:
                report.to_review += 1
                if ext not in reviewed and ext not in queued:
                    session.add(LinkCandidate(source_id=af.id, external_id=ext, external_name=e.full_name or e.name,
                                              candidate_player_id=best_id, similarity=score or None, reason=how[:100]))
                    queued.add(ext)
                continue

        # 2. quality gates
        if is_inconsistent(e.stats):
            report.inconsistent += 1
            continue
        key = (player_id, league.id)
        if key not in tm_main or tm_total[key] == 0:
            report.no_tm_minutes += 1
            continue
        api_minutes = e.stats["minutes"] or 0
        if not minutes_agree(api_minutes, tm_total[key]):
            report.held.append(f"{e.name} ({league.name}): API {api_minutes} vs TM {tm_total[key]} min [{e.origin}]")
            continue

        # 3. store, attributed to the Transfermarkt club with most league minutes
        rows.append({"player_id": player_id, "club_id": tm_main[key][0], "league_id": league.id, "season": season,
                     "source_id": af.id, "import_run_id": run.id, **e.stats})
        stored, regulars = report.per_league.get(league.name, (0, 0))
        report.per_league[league.name] = (stored + 1, regulars + (api_minutes >= 900))

    session.flush()
    for chunk in chunks(rows):  # sized to stay under PostgreSQL's 65,535-parameter limit
        session.execute(pg_insert(PlayerSeasonStats).values(chunk))
    report.stored = len(rows)

    run.status = "success"
    run.finished_at = datetime.now(timezone.utc)
    run.rows_written = report.stored
    session.flush()
    return report
