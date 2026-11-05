"""Presentation helpers shared by the CLI and the API (display only; never changes the optimum)."""

from app.optimization.model import ROLES, SLOTS, Team


def place(team: Team, formation: str | None) -> list[tuple[str, object]]:
    """Display order: pitch slots for a formation (left-footed full-back on the left), else by role."""
    if not formation:
        return [(p.role, p) for r in ROLES for p in sorted(team.players, key=lambda p: -p.score) if p.role == r]
    left = {p.player_id for p in team.players if p.role == "FB" and (p.foot or "").lower() == "left"}
    pools = {r: sorted([p for p in team.players if p.role == r],
                       key=lambda p: (p.player_id not in left, -p.score)) for r in ROLES}
    placed, extra = [], []
    for slot, role in SLOTS[formation]:
        placed.append((slot, pools[role].pop(0)))
    for r in ROLES:
        extra += [("SUB", p) for p in pools[r]]
    return placed + extra
