"""seed data sources and league configuration

Only identifiers verified in Phase 1b are filled in:
  * Transfermarkt competition codes: from the snapshot's competitions table (2026-11-04).
  * API-Football league ids: only the top 5, checked with /leagues on 2026-11-04.
Leagues beyond v1 stay disabled with apifootball_id NULL until they are verified.

Revision ID: 0002
Revises: 0001
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

data_source = sa.table(
    "data_source",
    sa.column("code", sa.String),
    sa.column("name", sa.String),
    sa.column("url", sa.String),
    sa.column("licence_note", sa.Text),
)

league = sa.table(
    "league",
    sa.column("name", sa.String),
    sa.column("country", sa.String),
    sa.column("tm_competition_id", sa.String),
    sa.column("apifootball_id", sa.Integer),
    sa.column("rollout_stage", sa.String),
    sa.column("enabled", sa.Boolean),
)

SOURCES = [
    {
        "code": "api_football",
        "name": "API-Football",
        "url": "https://www.api-football.com/",
        "licence_note": "Free plan, 100 requests/day, seasons 2022-2024. Subject to API-Football terms of use.",
    },
    {
        "code": "transfermarkt",
        "name": "Transfermarkt (via dcaribou/transfermarkt-datasets)",
        "url": "https://github.com/dcaribou/transfermarkt-datasets",
        "licence_note": "Community dataset of Transfermarkt data; snapshot to 2026-07-06, valuations to 2026-06-12. "
        "Academic, non-commercial use; do not redistribute.",
    },
    {
        "code": "clubelo",
        "name": "ClubElo",
        "url": "http://clubelo.com/",
        "licence_note": "Free public API; credit clubelo.com.",
    },
    {
        "code": "scoutiq",
        "name": "ScoutIQ (calculated or user-entered)",
        "url": None,
        "licence_note": "Values produced by ScoutIQ models or entered by users; not source data.",
    },
]

LEAGUES = [
    # v1 - enabled
    ("Premier League", "England", "GB1", 39, "v1", True),
    ("La Liga", "Spain", "ES1", 140, "v1", True),
    ("Serie A", "Italy", "IT1", 135, "v1", True),
    ("Bundesliga", "Germany", "L1", 78, "v1", True),
    ("Ligue 1", "France", "FR1", 61, "v1", True),
    # v1.5 - disabled until API-Football ids are verified
    ("Primeira Liga", "Portugal", "PO1", None, "v1.5", False),
    ("Eredivisie", "Netherlands", "NL1", None, "v1.5", False),
    ("Belgian Pro League", "Belgium", "BE1", None, "v1.5", False),
    ("Süper Lig", "Türkiye", "TR1", None, "v1.5", False),
    # v2
    ("Austrian Bundesliga", "Austria", "A1", None, "v2", False),
    ("Swiss Super League", "Switzerland", "C1", None, "v2", False),
    ("Ekstraklasa", "Poland", "PL1", None, "v2", False),
    ("SuperSport HNL", "Croatia", "KR1", None, "v2", False),
    ("Serbian SuperLiga", "Serbia", "SER1", None, "v2", False),
    ("Macedonian First League", "North Macedonia", None, None, "v2", False),
]


def upgrade() -> None:
    op.bulk_insert(data_source, SOURCES)
    op.bulk_insert(
        league,
        [
            {
                "name": name,
                "country": country,
                "tm_competition_id": tm,
                "apifootball_id": af,
                "rollout_stage": stage,
                "enabled": enabled,
            }
            for name, country, tm, af, stage, enabled in LEAGUES
        ],
    )


def downgrade() -> None:
    op.execute("DELETE FROM league")
    op.execute(
        "DELETE FROM data_source WHERE code IN ('api_football', 'transfermarkt', 'clubelo', 'scoutiq')"
    )
