"""Market calendar for CME equity index futures (MNQ1!, ES, NQ, etc.).

Used by scheduled jobs to skip weekends and full-day holidays before
spending a Thinking call or driving Chrome.

Covers full-day closures only — early closes (Black Friday, day before
Independence Day, Christmas Eve) are NOT flagged here. A forecast job
on an early-close day will still run; it just sees a truncated session
which the profile gate handles.

Update the HOLIDAYS dict annually. The check is a pure date-match so no
external dependency (pandas_market_calendars, etc.) is needed.
"""

from __future__ import annotations

from datetime import date, datetime


# CME Equity Index Futures full-day closures — New Year's Day, MLK, Presidents,
# Good Friday, Memorial, Juneteenth, Independence, Labor, Thanksgiving, Christmas.
# Source: CME holiday calendar.
HOLIDAYS: dict[int, set[date]] = {
    2026: {
        date(2026, 1, 1),   # New Year's Day
        date(2026, 1, 19),  # MLK Day
        date(2026, 2, 16),  # Presidents Day
        date(2026, 4, 3),   # Good Friday
        date(2026, 5, 25),  # Memorial Day
        date(2026, 6, 19),  # Juneteenth
        date(2026, 7, 3),   # Independence Day observed (Jul 4 = Sat)
        date(2026, 9, 7),   # Labor Day
        date(2026, 11, 26), # Thanksgiving
        date(2026, 12, 25), # Christmas
    },
    2027: {
        date(2027, 1, 1),   # New Year's Day
        date(2027, 1, 18),  # MLK Day
        date(2027, 2, 15),  # Presidents Day
        date(2027, 3, 26),  # Good Friday
        date(2027, 5, 31),  # Memorial Day
        date(2027, 6, 18),  # Juneteenth observed (Jun 19 = Sat)
        date(2027, 7, 5),   # Independence Day observed (Jul 4 = Sun)
        date(2027, 9, 6),   # Labor Day
        date(2027, 11, 25), # Thanksgiving
        date(2027, 12, 24), # Christmas observed (Dec 25 = Sat)
    },
}


def is_market_day(d: date | datetime | None = None) -> bool:
    """True when CME equity futures have a full RTH session on `d`.

    None → today's date in local time. Mon–Fri and not in HOLIDAYS → True.
    """
    if d is None:
        d = date.today()
    elif isinstance(d, datetime):
        d = d.date()
    if d.weekday() >= 5:  # Sat=5, Sun=6
        return False
    year_set = HOLIDAYS.get(d.year, set())
    return d not in year_set


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        d = datetime.strptime(sys.argv[1], "%Y-%m-%d").date()
    else:
        d = date.today()
    print(f"{d}: {'market day' if is_market_day(d) else 'holiday/weekend'}")
    sys.exit(0 if is_market_day(d) else 1)
