"""Find meeting windows that suit a group.

Each member's availability is a set of slots. A *window* is a run of consecutive slots on one
day, together with the members free for all of it. The planner returns windows that:

* last at least ``duration`` slots,
* include at least ``quorum`` members and every ``required`` member,
* are *maximal*: no other qualifying window covers the same time (or more) with the same
  members (or more). Without this rule, one free afternoon would come back as dozens of
  overlapping answers.

Results are ranked by number of attendees, then length, then earliest start.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

from .grid import SLOT_COUNT, SLOTS_PER_DAY


@dataclass(frozen=True)
class Window:
    start: int            # first slot
    end: int              # one past the last slot
    members: frozenset    # member ids free for the whole window

    @property
    def length(self) -> int:
        return self.end - self.start

    def covers(self, other: "Window") -> bool:
        return (self.start <= other.start and other.end <= self.end
                and other.members <= self.members)


def find_windows(availability: Mapping[int, Iterable[int]], duration: int, quorum: int,
                 required: Iterable[int] = (), limit: int | None = 10) -> list[Window]:
    if duration < 1:
        raise ValueError("duration must be at least one slot")
    if quorum < 1:
        raise ValueError("quorum must be at least 1")
    ids = sorted(availability)
    bit = {member: 1 << i for i, member in enumerate(ids)}
    need = 0
    for member in required:
        if member not in bit:
            raise ValueError(f"unknown required member {member}")
        need |= bit[member]

    # free[s]: bitmask of members free in slot s.
    free = [0] * SLOT_COUNT
    for member, slots in availability.items():
        for s in slots:
            free[s] |= bit[member]

    result: list[Window] = []
    for day_start in range(0, SLOT_COUNT, SLOTS_PER_DAY):
        day_end = day_start + SLOTS_PER_DAY
        candidates: list[tuple[int, int, int]] = []
        for start in range(day_start, day_end):
            mask = -1
            for s in range(start, day_end):
                narrowed = mask & free[s]
                if narrowed.bit_count() < quorum or narrowed & need != need:
                    break
                mask = narrowed
                # Record the longest run from `start` with this exact member set: the set
                # is about to shrink (or the day/condition ends) after slot s.
                last = s + 1 == day_end or (mask & free[s + 1]) != mask
                if last and s + 1 - start >= duration:
                    candidates.append((start, s + 1, mask))
        # A candidate starting at `start` may still sit inside one that starts earlier with
        # the same or more members (both free 10:00-12:00 is inside both free 09:00-12:00).
        # Windows never cross midnight, so only the same day's candidates can cover it.
        for a, b, m in candidates:
            if not any(a2 <= a and b <= b2 and m & m2 == m and (a2, b2, m2) != (a, b, m)
                       for a2, b2, m2 in candidates):
                result.append(Window(a, b, _members(m, ids)))
    result.sort(key=lambda w: (-len(w.members), -w.length, w.start))
    return result if limit is None else result[:limit]


def _members(mask: int, ids: list[int]) -> frozenset:
    return frozenset(member for i, member in enumerate(ids) if mask >> i & 1)
