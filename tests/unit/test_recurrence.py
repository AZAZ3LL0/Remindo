"""Invariants of next_occurrences (tech.md 10)."""

from datetime import UTC, datetime, timedelta
from itertools import pairwise
from zoneinfo import ZoneInfo

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from app.domain.recurrence import next_occurrences, to_utc
from app.domain.schedules import (
    DailySchedule,
    IntervalSchedule,
    WeeklySchedule,
    parse_schedule,
)
from tests.unit.strategies import ranges, schedules, timezones, wall_clock_schedules

SLOW = settings(max_examples=40, deadline=None, suppress_health_check=[HealthCheck.too_slow])


def offset_changes_that_day(moment: datetime, tz: ZoneInfo) -> bool:
    """True when the local date of `moment` contains a UTC offset transition."""
    local = moment.astimezone(tz)
    start = datetime.combine(local.date(), datetime.min.time(), tzinfo=tz)
    return start.utcoffset() != (start + timedelta(days=1)).utcoffset()


@SLOW
@given(schedule=schedules, tz=timezones, window=ranges(), limit=st.integers(1, 50))
def test_result_is_sorted_unique_and_bounded(schedule, tz, window, limit):
    after, until = window
    result = next_occurrences(schedule, tz, after=after, until=until, limit=limit)

    assert len(result) <= limit
    assert result == sorted(result)
    assert len(set(result)) == len(result)
    for moment in result:
        assert moment.tzinfo is not None
        assert moment.utcoffset() == timedelta(0)
        assert after < moment <= until


@SLOW
@given(schedule=schedules, tz=timezones, window=ranges(), limit=st.integers(1, 20))
def test_is_deterministic(schedule, tz, window, limit):
    after, until = window
    first = next_occurrences(schedule, tz, after=after, until=until, limit=limit)
    second = next_occurrences(schedule, tz, after=after, until=until, limit=limit)
    assert first == second


@SLOW
@given(schedule=schedules, tz=timezones, window=ranges(max_days=6))
def test_range_splits_without_gaps_or_duplicates(schedule, tz, window):
    """(a, c] equals (a, b] concatenated with (b, c]."""
    after, until = window
    middle = after + (until - after) / 2
    middle = middle.replace(second=0, microsecond=0)

    whole = next_occurrences(schedule, tz, after=after, until=until, limit=1000)
    first = next_occurrences(schedule, tz, after=after, until=middle, limit=1000)
    second = next_occurrences(schedule, tz, after=middle, until=until, limit=1000)

    assert whole == first + second


@SLOW
@given(schedule=wall_clock_schedules, tz=timezones, window=ranges(max_days=10))
def test_wall_clock_time_survives(schedule, tz, window):
    """Rule 1: 07:30 stays 07:30, except where the local clock jumps."""
    after, until = window
    for moment in next_occurrences(schedule, tz, after=after, until=until, limit=100):
        if offset_changes_that_day(moment, tz):
            continue
        assert moment.astimezone(tz).time() in schedule.times


@SLOW
@given(
    schedule=st.builds(
        IntervalSchedule,
        every_minutes=st.integers(min_value=5, max_value=720),
        window_start=st.just("09:00"),
        window_end=st.just("21:00"),
    ),
    tz=timezones,
    window=ranges(max_days=10),
)
def test_interval_never_fires_denser_than_the_interval(schedule, tz, window):
    after, until = window
    result = next_occurrences(schedule, tz, after=after, until=until, limit=200)
    step = timedelta(minutes=schedule.every_minutes)
    for previous, current in pairwise(result):
        assert current - previous >= step


def test_interval_keeps_absolute_spacing_across_spring_forward():
    """Rule 2: the absolute interval wins for interval schedules."""
    tz = ZoneInfo("Europe/Berlin")
    schedule = IntervalSchedule(every_minutes=60, window_start="00:00", window_end="00:00")
    result = next_occurrences(
        schedule,
        tz,
        after=datetime(2026, 3, 28, 22, 0, tzinfo=UTC),
        until=datetime(2026, 3, 29, 6, 0, tzinfo=UTC),
        limit=50,
    )
    for previous, current in pairwise(result):
        assert current - previous == timedelta(hours=1)


def test_daily_keeps_wall_clock_across_spring_forward():
    tz = ZoneInfo("Europe/Berlin")
    schedule = DailySchedule(times=["07:30"], every_n_days=1)
    result = next_occurrences(
        schedule,
        tz,
        after=datetime(2026, 3, 27, 0, 0, tzinfo=UTC),
        until=datetime(2026, 3, 31, 0, 0, tzinfo=UTC),
        limit=10,
    )
    assert [moment.astimezone(tz).strftime("%d %H:%M %z") for moment in result] == [
        "27 07:30 +0100",
        "28 07:30 +0100",
        "29 07:30 +0200",
        "30 07:30 +0200",
    ]


def test_nonexistent_local_time_moves_to_the_first_existing_moment():
    """Rule 3: 02:30 does not exist on the spring-forward night."""
    tz = ZoneInfo("Europe/Berlin")
    moved = to_utc(datetime(2026, 3, 29, 2, 30), tz)
    assert moved.astimezone(tz) == datetime(2026, 3, 29, 3, 0, tzinfo=tz)


def test_ambiguous_local_time_takes_the_earlier_offset():
    """Rule 4: 02:30 happens twice on the fall-back night; the first one wins."""
    tz = ZoneInfo("Europe/Berlin")
    resolved = to_utc(datetime(2026, 10, 25, 2, 30), tz)
    assert resolved == datetime(2026, 10, 25, 0, 30, tzinfo=UTC)


def test_monthly_maps_missing_days_onto_the_last_day():
    tz = ZoneInfo("UTC")
    schedule = parse_schedule(
        {"kind": "monthly", "times": ["10:00"], "days": [31], "on_missing_day": "last_day"}
    )
    result = next_occurrences(
        schedule,
        tz,
        after=datetime(2026, 2, 1, tzinfo=UTC),
        until=datetime(2026, 3, 1, tzinfo=UTC),
        limit=5,
    )
    assert [moment.date().isoformat() for moment in result] == ["2026-02-28"]


def test_monthly_skips_missing_days_when_asked():
    tz = ZoneInfo("UTC")
    schedule = parse_schedule(
        {"kind": "monthly", "times": ["10:00"], "days": [31], "on_missing_day": "skip"}
    )
    result = next_occurrences(
        schedule,
        tz,
        after=datetime(2026, 2, 1, tzinfo=UTC),
        until=datetime(2026, 3, 1, tzinfo=UTC),
        limit=5,
    )
    assert result == []


def test_weekly_fires_only_on_selected_weekdays():
    tz = ZoneInfo("UTC")
    schedule = WeeklySchedule(times=["07:30"], weekdays=[1, 3])
    result = next_occurrences(
        schedule,
        tz,
        after=datetime(2026, 6, 1, tzinfo=UTC),
        until=datetime(2026, 6, 9, tzinfo=UTC),
        limit=10,
    )
    assert [moment.isoweekday() for moment in result] == [1, 3, 1]


def test_naive_bounds_are_rejected():
    with pytest.raises(ValueError, match="timezone-aware"):
        next_occurrences(
            DailySchedule(times=["08:00"]),
            ZoneInfo("UTC"),
            after=datetime(2026, 1, 1),
            until=datetime(2026, 1, 2, tzinfo=UTC),
            limit=5,
        )
