"""Hypothesis strategies for dates and schedules. Declared once, reused everywhere."""

from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from hypothesis import strategies as st

from app.domain.schedules import (
    DailySchedule,
    IntervalSchedule,
    MonthlySchedule,
    OnceSchedule,
    WeeklySchedule,
)

#: Zones with awkward transitions: half-hour offsets, southern hemisphere, DST.
TIMEZONE_NAMES = (
    "UTC",
    "Europe/Berlin",
    "Europe/Moscow",
    "America/New_York",
    "Australia/Lord_Howe",
    "Pacific/Chatham",
    "Asia/Kolkata",
)

timezones = st.sampled_from(TIMEZONE_NAMES).map(ZoneInfo)

local_times = st.builds(
    time, hour=st.integers(min_value=0, max_value=23), minute=st.integers(0, 59)
)

hhmm = local_times.map(lambda value: f"{value.hour:02d}:{value.minute:02d}")

#: A window wide enough for DST shifts to matter, anchored inside one day.
utc_moments = st.datetimes(
    min_value=datetime(2024, 1, 1),
    max_value=datetime(2030, 12, 31),
).map(lambda value: value.replace(second=0, microsecond=0, tzinfo=UTC))

time_lists = st.lists(hhmm, min_size=1, max_size=12, unique=True)


once_schedules = st.builds(
    OnceSchedule,
    at=st.datetimes(min_value=datetime(2024, 1, 1), max_value=datetime(2030, 12, 31)).map(
        lambda value: value.replace(second=0, microsecond=0).strftime("%Y-%m-%dT%H:%M")
    ),
)

interval_schedules = st.builds(
    IntervalSchedule,
    every_minutes=st.integers(min_value=5, max_value=1440),
    window_start=hhmm,
    window_end=hhmm,
)

daily_schedules = st.builds(
    DailySchedule,
    times=time_lists,
    every_n_days=st.integers(min_value=1, max_value=7),
)

weekly_schedules = st.builds(
    WeeklySchedule,
    times=time_lists,
    weekdays=st.lists(st.integers(min_value=1, max_value=7), min_size=1, max_size=7, unique=True),
)

monthly_schedules = st.builds(
    MonthlySchedule,
    times=time_lists,
    days=st.lists(st.integers(min_value=1, max_value=31), min_size=1, max_size=6, unique=True),
    on_missing_day=st.sampled_from(["last_day", "skip"]),
)

wall_clock_schedules = st.one_of(daily_schedules, weekly_schedules, monthly_schedules)

schedules = st.one_of(
    once_schedules, interval_schedules, daily_schedules, weekly_schedules, monthly_schedules
)


@st.composite
def ranges(draw: st.DrawFn, max_days: int = 14) -> tuple[datetime, datetime]:
    """A (after, until] range of bounded length."""
    after = draw(utc_moments)
    span = draw(st.integers(min_value=1, max_value=max_days * 24 * 60))
    return after, after + timedelta(minutes=span)
