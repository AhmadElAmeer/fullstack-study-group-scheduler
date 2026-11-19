import random

import pytest

from scheduler.grid import SLOTS_PER_DAY as D, clock, describe
from scheduler.planner import Window, find_windows


def run(*ranges):
    """Slots from (day, start_index, end_index) ranges."""
    return {d * D + i for d, a, b in ranges for i in range(a, b)}


def test_grid_layout():
    assert D == 28
    assert clock(0) == "08:00" and clock(1) == "08:30" and clock(28) == "22:00"
    g = describe()
    assert g["days"][0] == "Sun" and len(g["times"]) == 29


def test_overlap_of_two_people():
    avail = {1: run((1, 4, 12)), 2: run((1, 6, 14))}  # Mon 10-14 and Mon 11-15
    w = find_windows(avail, duration=2, quorum=2)
    assert w == [Window(D + 6, D + 12, frozenset({1, 2}))]


def test_windows_are_maximal_and_ranked():
    avail = {1: run((1, 4, 12)), 2: run((1, 6, 14)), 3: run((1, 2, 10))}
    w = find_windows(avail, duration=3, quorum=2, limit=None)
    # Everyone 11:00-13:00 first; then the pairs, longest first; Omar+Lina's 11-13 is
    # covered by the three-person window, so it's not repeated.
    assert [(x.start - D, x.end - D, sorted(x.members)) for x in w] == [
        (6, 10, [1, 2, 3]),
        (4, 10, [1, 3]),
        (6, 12, [1, 2]),
    ]


def test_duration_quorum_and_required():
    avail = {1: run((0, 0, 4)), 2: run((0, 0, 2)), 3: run((0, 0, 6))}
    assert find_windows(avail, duration=5, quorum=2) == []
    assert find_windows(avail, duration=5, quorum=1) == [Window(0, 6, frozenset({3}))]
    only_1 = find_windows(avail, duration=1, quorum=1, required=[1], limit=None)
    assert all(1 in w.members for w in only_1)
    assert Window(0, 2, frozenset({1, 2, 3})) in only_1
    with pytest.raises(ValueError):
        find_windows(avail, duration=1, quorum=1, required=[99])
    with pytest.raises(ValueError):
        find_windows(avail, duration=0, quorum=1)
    with pytest.raises(ValueError):
        find_windows(avail, duration=1, quorum=0)


def test_windows_never_cross_midnight():
    # Free from Sunday 21:00 to Monday 09:00: two separate one-hour windows, not one.
    avail = {1: {D - 2, D - 1, D, D + 1}}
    assert find_windows(avail, duration=2, quorum=1, limit=None) == [
        Window(D - 2, D, frozenset({1})), Window(D, D + 2, frozenset({1}))]
    assert find_windows(avail, duration=3, quorum=1) == []


def test_limit_and_empty():
    avail = {1: run(*[(d, 0, 2) for d in range(7)])}
    assert len(find_windows(avail, duration=1, quorum=1)) == 7
    assert len(find_windows(avail, duration=1, quorum=1, limit=3)) == 3
    assert find_windows({1: set(), 2: set()}, duration=1, quorum=1) == []


def brute_force(avail, duration, quorum, required):
    """The definition, checked literally: every interval, its attendees, then drop covered ones."""
    found = []
    for day in range(7):
        windows = []
        for a in range(day * D, day * D + D):
            for b in range(a + duration, day * D + D + 1):
                members = frozenset(m for m, slots in avail.items() if all(s in slots for s in range(a, b)))
                if len(members) >= quorum and set(required) <= members:
                    windows.append(Window(a, b, members))
        found += [w for w in windows if not any(o != w and o.covers(w) for o in windows)]
    return set(found)


def random_week(rng, members):
    avail = {}
    for m in range(members):
        slots = set()
        for _ in range(rng.randint(1, 8)):           # a few free blocks per week
            day, start = rng.randrange(3), rng.randrange(D)   # 3 busy days, so blocks overlap
            slots |= {day * D + i for i in range(start, min(D, start + rng.randint(2, 14)))}
        slots |= {rng.randrange(7 * D) for _ in range(rng.randint(0, 5))}  # plus scattered slots
        avail[m * 7 + 3] = slots                       # ids needn't be 0..n-1
    return avail


@pytest.mark.parametrize("seed", range(150))
def test_matches_brute_force(seed):
    rng = random.Random(seed)
    avail = random_week(rng, rng.randint(1, 5))
    ids = sorted(avail)
    duration = rng.randint(1, 6)
    quorum = rng.randint(1, rng.randint(1, len(ids)))  # biased low, so windows exist
    required = rng.sample(ids, rng.randint(0, min(2, len(ids))))
    got = find_windows(avail, duration, quorum, required, limit=None)
    assert len(got) == len(set(got)), "duplicates"
    assert set(got) == brute_force(avail, duration, quorum, required)
    keys = [(-len(w.members), -w.length, w.start) for w in got]
    assert keys == sorted(keys)
