"""Split multi-row INSERTs so one statement never exceeds PostgreSQL's limit of 65,535 parameters.

A multi-row INSERT ... VALUES (...), (...) sends rows x columns parameters. The batch size therefore
depends on the column count: 38 columns allow at most 1,724 rows per statement.
"""

from collections.abc import Iterator, Sequence

PG_MAX_PARAMS = 65_535


def chunks(rows: Sequence[dict], max_params: int = PG_MAX_PARAMS) -> Iterator[Sequence[dict]]:
    """Yield consecutive slices of rows, each small enough for one statement."""
    if not rows:
        return
    columns = max(len(r) for r in rows)
    size = max(1, max_params // columns)
    for start in range(0, len(rows), size):
        yield rows[start : start + size]
