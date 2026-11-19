"""The weekly grid: 7 days x 28 half-hour slots from 08:00 to 22:00.

A slot is one integer, ``day * SLOTS_PER_DAY + index``, so Sunday 08:00 is 0 and Saturday
21:30 is 195. Weeks start on Sunday.
"""

DAYS = ("Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat")
DAY_START_MIN = 8 * 60
DAY_END_MIN = 22 * 60
SLOT_MIN = 30
SLOTS_PER_DAY = (DAY_END_MIN - DAY_START_MIN) // SLOT_MIN  # 28
SLOT_COUNT = len(DAYS) * SLOTS_PER_DAY                      # 196


def day_of(slot: int) -> int:
    return slot // SLOTS_PER_DAY


def clock(index_in_day: int) -> str:
    """Start time of the slot with this index within its day; 28 gives the day's end, 22:00."""
    minutes = DAY_START_MIN + index_in_day * SLOT_MIN
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def describe() -> dict:
    """What the browser needs to draw the grid."""
    return {
        "days": list(DAYS),
        "times": [clock(i) for i in range(SLOTS_PER_DAY + 1)],
        "slot_minutes": SLOT_MIN,
        "slots_per_day": SLOTS_PER_DAY,
    }
