"""Simpler selection methods to compare the optimizer with, plus exhaustive search for tests.

All greedy baselines see the same candidates and constraints as the optimizer and keep
enough money in reserve to fill the remaining places at the cheapest prices, so they do
not paint themselves into an infeasible corner.
"""

import itertools
import random
from collections import Counter, defaultdict

from app.optimization.model import ROLES, Candidate, Request, Team, apply_filters


class _State:
    """Greedy bookkeeping shared by the baselines."""

    def __init__(self, pool: list[Candidate], kept: list[Candidate], req: Request):
        self.req = req
        self.kept_ids = frozenset(k.player_id for k in kept)
        self.chosen: list[Candidate] = list(kept)
        self.taken = {k.player_id for k in kept}
        self.counts = Counter(k.role for k in kept)
        self.clubs = Counter(k.club_id for k in kept if k.club_id is not None)
        self.money = req.budget
        self.by_role = defaultdict(list)
        for c in sorted(pool, key=lambda c: c.price):
            if c.player_id not in self.taken:
                self.by_role[c.role].append(c)
        self.cheapest_all = sorted((c for c in pool if c.player_id not in self.taken), key=lambda c: c.price)

    def full(self) -> bool:
        return len(self.chosen) >= self.req.squad_size

    def _reserve(self, counts: Counter, taken: set, slots_left: int) -> float:
        """Cheapest cost of filling the remaining minimums, then any remaining places."""
        cost, used = 0, set()
        for r in ROLES:
            need = max(0, self.req.role_min.get(r, 0) - counts.get(r, 0))
            got = 0
            for c in self.by_role[r]:
                if got == need:
                    break
                if c.player_id not in taken:
                    cost += c.price
                    used.add(c.player_id)
                    got += 1
            if got < need:
                return float("inf")
            slots_left -= need
        for c in self.cheapest_all:
            if slots_left <= 0:
                break
            if c.player_id not in taken and c.player_id not in used and counts.get(c.role, 0) < self.req.role_max.get(c.role, 0):
                cost += c.price
                slots_left -= 1
        return cost if slots_left <= 0 else float("inf")

    def can_take(self, c: Candidate) -> bool:
        req = self.req
        if c.player_id in self.taken or self.counts.get(c.role, 0) >= req.role_max.get(c.role, 0):
            return False
        if req.max_per_club is not None and c.club_id is not None and self.clubs.get(c.club_id, 0) >= req.max_per_club:
            return False
        if c.price > self.money:
            return False
        counts = self.counts.copy()
        counts[c.role] += 1
        slots_left = req.squad_size - len(self.chosen) - 1
        unmet = sum(max(0, req.role_min.get(r, 0) - counts.get(r, 0)) for r in ROLES)
        if unmet > slots_left:
            return False
        return c.price + self._reserve(counts, self.taken | {c.player_id}, slots_left) <= self.money

    def take(self, c: Candidate) -> None:
        self.chosen.append(c)
        self.taken.add(c.player_id)
        self.counts[c.role] += 1
        if c.club_id is not None:
            self.clubs[c.club_id] += 1
        self.money -= c.price

    def team(self) -> Team | None:
        return Team(self.chosen, self.kept_ids) if self.full() else None


def best_affordable_per_position(candidates, req: Request, kept=None) -> Team | None:
    """Fill places role by role (GK, CB, FB, CM, AW, ST), each time taking the best affordable player."""
    kept = kept or []
    pool = apply_filters(candidates, req)
    st = _State(pool, kept, req)
    by_score = sorted(pool, key=lambda c: -c.score)
    slots = [r for r in ROLES for _ in range(max(0, req.role_min.get(r, 0) - st.counts.get(r, 0)))]
    slots += [None] * (req.squad_size - len(kept) - len(slots))  # extra places: any role with room
    for role in slots:
        pick = next((c for c in by_score if (role is None or c.role == role) and st.can_take(c)), None)
        if pick is None:
            return None
        st.take(pick)
    return st.team()


def greedy_value(candidates, req: Request, kept=None) -> Team | None:
    """Repeatedly take the player with the highest score per euro whose role still has a place."""
    kept = kept or []
    pool = apply_filters(candidates, req)
    st = _State(pool, kept, req)
    for c in sorted(pool, key=lambda c: -c.score / max(c.price, 1_000)):
        if st.full():
            break
        if st.can_take(c):
            st.take(c)
    return st.team()


def random_feasible(candidates, req: Request, kept=None, tries: int = 100, seed: int = 0) -> Team | None:
    """Testing floor: best of `tries` random valid teams."""
    kept = kept or []
    pool = apply_filters(candidates, req)
    rng = random.Random(seed)
    best = None
    for _ in range(tries):
        order = pool[:]
        rng.shuffle(order)
        st = _State(pool, kept, req)
        for c in order:
            if st.full():
                break
            if st.can_take(c):
                st.take(c)
        t = st.team()
        if t and (best is None or (t.total_score, -t.cost) > (best.total_score, -best.cost)):
            best = t
    return best


def brute_force(candidates, req: Request, kept=None, limit: int = 3_000_000) -> Team | None:
    """Exhaustive search over all role-valid combinations (fixed role counts only). For tests."""
    kept = kept or []
    if req.role_min != req.role_max:
        raise ValueError("brute force supports fixed role counts only")
    pool = apply_filters(candidates, req)
    kept_roles = Counter(k.role for k in kept)
    groups = []
    for r in ROLES:
        need = req.role_min.get(r, 0) - kept_roles.get(r, 0)
        if need < 0:
            return None
        groups.append(list(itertools.combinations([c for c in pool if c.role == r], need)))
    size = 1
    for g in groups:
        size *= max(len(g), 1)
    if size > limit:
        raise ValueError(f"{size} combinations: pool too large for brute force")
    best, best_key = None, None
    for combo in itertools.product(*groups):
        players = list(kept) + [c for part in combo for c in part]
        cost = sum(c.price for c in players if c not in kept)
        if cost > req.budget:
            continue
        if req.max_per_club is not None and any(
                n > req.max_per_club for n in Counter(c.club_id for c in players if c.club_id is not None).values()):
            continue
        key = (round(sum(c.score for c in players), 6), -cost)
        if best_key is None or key > best_key:
            best, best_key = players, key
    return None if best is None else Team(best, frozenset(k.player_id for k in kept))
