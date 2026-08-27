"""Pure expansion of a schedule into firing moments.

Rules of time (tech.md 5.1):

1. wall-clock wins for `once`, `daily`, `weekly`, `monthly`: 07:30 stays 07:30
   across DST transitions;
2. the absolute interval wins for `interval`: consecutive moments inside one
   activity window are exactly `every_minutes` apart;
3. a nonexistent local time (spring forward) moves to the first existing moment;
4. an ambiguous local time (fall back) takes the first, earlier offset;
5. the result is UTC-aware, strictly increasing and free of duplicates.
"""

import calendar
from collections.abc import Iterator
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.domain.schedules import (
    DailySchedule,
    IntervalSchedule,
    MonthlySchedule,
    OnceSchedule,
    Schedule,
    WeeklySchedule,
)

#: Anchor for `every_n_days`. The schedule contract carries no anchor date, so
#: the phase is pinned to a fixed epoch and the function stays pure.
_DAY_EPOCH = date(1970, 1, 1)

#: More candidates than the densest schedule can produce in two local days
#: (a 24h window at every_minutes=5 yields 288). Once this many valid moments
#: are collected, no later local date can displace the first `limit` of them.
_SAFETY_BUFFER = 600

#: Guard against unbounded ranges; callers plan against a horizon.
_MAX_LOCAL_DAYS = 3660


def to_utc(naive: datetime, tz: ZoneInfo) -> datetime:
    """Resolve a local wall-clock moment to UTC, applying rules 3 and 4."""
    early = naive.replace(tzinfo=tz, fold=0)
    late = naive.replace(tzinfo=tz, fold=1)
    offset_early = early.utcoffset()
    offset_late = late.utcoffset()

    if offset_early == offset_late:
        return early.astimezone(UTC)
    if offset_early is not None and offset_late is not None and offset_early > offset_late:
        # Ambiguous: the earlier offset maps to the earlier instant.
        return early.astimezone(UTC)
    return _first_existing_moment(naive, tz, low=late, high=early)


def _first_existing_moment(
    naive: datetime, tz: ZoneInfo, low: datetime, high: datetime
) -> datetime:
    """Smallest instant whose local time is at or after a nonexistent `naive`.

    The local clock jumps over the gap, so the answer is the transition instant
    itself. Offsets change on whole seconds, which makes an integer bisection
    exact.
    """
    low_ts = int(low.timestamp())
    high_ts = int(high.timestamp())
    while high_ts - low_ts > 1:
        mid_ts = (low_ts + high_ts) // 2
        mid = datetime.fromtimestamp(mid_ts, UTC)
        if mid.astimezone(tz).replace(tzinfo=None) >= naive:
            high_ts = mid_ts
        else:
            low_ts = mid_ts
    return datetime.fromtimestamp(high_ts, UTC)


def next_occurrences(
    schedule: Schedule,
    tz: ZoneInfo,
    after: datetime,
    until: datetime,
    limit: int,
) -> list[datetime]:
    """Firing moments in the half-open range (after, until], ascending UTC."""
    if after.tzinfo is None or until.tzinfo is None:
        raise ValueError("after and until must be timezone-aware")
    if limit <= 0 or until <= after:
        return []

    after = after.astimezone(UTC)
    until = until.astimezone(UTC)

    if isinstance(schedule, OnceSchedule):
        moment = to_utc(schedule.at, tz)
        return [moment] if after < moment <= until else []

    found: set[datetime] = set()
    for local_day in _local_days(tz, after, until):
        for moment in _moments_for_day(schedule, tz, local_day):
            if after < moment <= until:
                found.add(moment)
        if len(found) >= limit + _SAFETY_BUFFER:
            break

    return sorted(found)[:limit]


def _local_days(tz: ZoneInfo, after: datetime, until: datetime) -> Iterator[date]:
    """Local dates that can contribute to the range, with a margin for offsets."""
    first = (after.astimezone(tz) - timedelta(days=1)).date()
    last = (until.astimezone(tz) + timedelta(days=1)).date()
    span = min((last - first).days, _MAX_LOCAL_DAYS)
    for offset in range(span + 1):
        yield first + timedelta(days=offset)


def _moments_for_day(schedule: Schedule, tz: ZoneInfo, day: date) -> list[datetime]:
    if isinstance(schedule, IntervalSchedule):
        return _interval_moments(schedule, tz, day)
    if isinstance(schedule, DailySchedule):
        if (day - _DAY_EPOCH).days % schedule.every_n_days:
            return []
        return [to_utc(datetime.combine(day, moment), tz) for moment in schedule.times]
    if isinstance(schedule, WeeklySchedule):
        if day.isoweekday() not in schedule.weekdays:
            return []
        return [to_utc(datetime.combine(day, moment), tz) for moment in schedule.times]
    if isinstance(schedule, MonthlySchedule):
        return _monthly_moments(schedule, tz, day)
    return []


def _interval_moments(schedule: IntervalSchedule, tz: ZoneInfo, day: date) -> list[datetime]:
    """One activity window anchored on `day`, stepped by an absolute interval."""
    start = to_utc(datetime.combine(day, schedule.window_start), tz)
    end_day = day if schedule.window_end > schedule.window_start else day + timedelta(days=1)
    end = to_utc(datetime.combine(end_day, schedule.window_end), tz)
    if end <= start:
        # Zero-length window: the anchor alone fires.
        return [start]

    step = timedelta(minutes=schedule.every_minutes)
    moments: list[datetime] = []
    current = start
    while current <= end:
        moments.append(current)
        current += step
    return moments


def _monthly_moments(schedule: MonthlySchedule, tz: ZoneInfo, day: date) -> list[datetime]:
    days_in_month = calendar.monthrange(day.year, day.month)[1]
    wanted: set[int] = set()
    for wanted_day in schedule.days:
        if wanted_day <= days_in_month:
            wanted.add(wanted_day)
        elif schedule.on_missing_day == "last_day":
            wanted.add(days_in_month)
    if day.day not in wanted:
        return []
    return [to_utc(datetime.combine(day, moment), tz) for moment in schedule.times]


def local_time_of(moment: datetime, tz: ZoneInfo) -> time:
    """Local wall-clock time of a UTC moment. Used by renderers and tests."""
    return moment.astimezone(tz).time()
