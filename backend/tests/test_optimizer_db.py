"""End-to-end: scored players in the database -> candidates -> optimal, verified team."""

import pytest
from sqlalchemy.orm import Session

from app.db.session import engine
from app.optimization.candidates import load_candidates
from app.optimization.model import positions_request
from app.optimization.solver import solve
from app.scoring.run import run as score_run
from tests.test_scoring import _seed_centre_backs


@pytest.fixture
def db():
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    yield session
    session.close()
    transaction.rollback()
    connection.close()


def test_database_candidates_to_verified_team(db):
    _seed_centre_backs(db, n=12)  # values EUR 1m..12m, better defenders cost more
    score_run(db, 2024)
    candidates = load_candidates(db, 2024)
    assert len(candidates) == 12 and all(c.role == "CB" and c.price > 0 for c in candidates)

    sol = solve(candidates, positions_request({"CB": 2}, 10_000_000))
    assert sol.status == "optimal" and sol.violations == []
    assert sol.team.cost <= 10_000_000 and len(sol.team.players) == 2

    impossible = solve(candidates, positions_request({"CB": 2}, 1_000_000))
    assert impossible.status == "infeasible"
    assert impossible.diagnosis["cheapest_cost"] == 3_000_000  # EUR 1m + 2m


def test_adjusted_score_without_calibration_gives_no_candidates(db):
    _seed_centre_backs(db, n=12)
    score_run(db, 2024)
    assert load_candidates(db, 2024, score="adjusted") == []  # never an unsupported cross-league score
