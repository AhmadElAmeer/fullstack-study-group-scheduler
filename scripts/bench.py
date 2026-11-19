"""Measure the suggestions endpoint and what the "maximal windows" rule saves.

Groups of 5, 20 and 60 members get a random week shaped like a student's: on each weekday
evening (Sun-Thu) a 55% chance of being free from about 17:00 to 21:00 (start and end vary
by up to an hour), on Fri/Sat a 35% chance of a 3-6 hour daytime block, plus 0-3 short
blocks and a few scattered half-hours. Seeded, so reruns use the same weeks. Times are medians of 50 requests through Flask's test client (routing,
SQLite query, planner, JSON), after 5 warm-up requests.
"""

import platform
import random
import statistics
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scheduler import create_app  # noqa: E402
from scheduler.grid import SLOTS_PER_DAY as D, SLOT_COUNT  # noqa: E402
from scheduler.planner import find_windows  # noqa: E402


def week(rng):
    slots = set()
    for day in range(5):                                   # Sun-Thu evenings
        if rng.random() < 0.55:
            start = 18 + rng.randint(-2, 2)                # 17:00 +- 1h, in half-hour slots
            end = 26 + rng.randint(-2, 2)                  # 21:00 +- 1h
            slots |= {day * D + i for i in range(start, min(D, end))}
    for day in (5, 6):                                     # Fri, Sat
        if rng.random() < 0.35:
            start = rng.randint(2, 14)
            slots |= {day * D + i for i in range(start, min(D, start + rng.randint(6, 12)))}
    for _ in range(rng.randint(0, 3)):
        day, start = rng.randrange(7), rng.randrange(D)
        slots |= {day * D + i for i in range(start, min(D, start + rng.randint(2, 6)))}
    slots |= {rng.randrange(SLOT_COUNT) for _ in range(rng.randint(0, 4))}
    return sorted(slots)


def all_qualifying(avail, duration, quorum):
    """Every interval that qualifies, before the maximal-window rule (what a naive tool lists)."""
    n = 0
    for day in range(7):
        for a in range(day * D, day * D + D):
            for b in range(a + duration, day * D + D + 1):
                if sum(all(s in slots for s in range(a, b)) for slots in avail.values()) >= quorum:
                    n += 1
    return n


def main():
    print(f"Python {platform.python_version()}, SQLite via sqlite3, {platform.machine()}")
    print(f"{'members':>7} {'quorum':>6} {'length':>6} {'request (ms)':>13} {'planner (ms)':>13} "
          f"{'qualifying intervals':>21} {'maximal windows':>16} {'best window':>30}")
    with tempfile.TemporaryDirectory() as tmp:
        app = create_app(str(Path(tmp) / "bench.db"))
        client = app.test_client()
        for size in (5, 20, 60):
            rng = random.Random(size)
            slug = client.post("/api/groups", json={"name": f"bench {size}"}).json["slug"]
            avail = {}
            for i in range(size):
                m = client.post(f"/api/groups/{slug}/members", json={"name": f"member {i}"}).json
                slots = week(rng)
                client.put(f"/api/groups/{slug}/members/{m['id']}/availability", json={"slots": slots},
                           headers={"X-Member-Key": m["key"]})
                avail[m["id"]] = set(slots)
            for minutes, quorum in ((60, (size + 1) // 2), (120, (size + 1) // 2), (60, 1)):
                url = f"/api/groups/{slug}/suggestions?duration={minutes}&quorum={quorum}&limit=50"
                for _ in range(5):
                    client.get(url)
                req = []
                for _ in range(50):
                    t = time.perf_counter()
                    r = client.get(url)
                    req.append((time.perf_counter() - t) * 1000)
                plan = []
                for _ in range(50):
                    t = time.perf_counter()
                    found = find_windows(avail, minutes // 30, quorum, limit=None)
                    plan.append((time.perf_counter() - t) * 1000)
                best = r.json["windows"][0] if r.json["windows"] else None
                best_s = f"{best['day']} {best['start']}-{best['end']}, {len(best['attendees'])} people" if best else "-"
                print(f"{size:>7} {quorum:>6} {minutes:>4}m {statistics.median(req):>13.2f} "
                      f"{statistics.median(plan):>13.2f} {all_qualifying(avail, minutes // 30, quorum):>21,} "
                      f"{len(found):>16,} {best_s:>30}")


if __name__ == "__main__":
    main()
