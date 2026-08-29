"""Hypothesis strategies for dates, schedules and categories.

Declared once, reused everywhere.
"""

from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from hypothesis import strategies as st

from app.domain.contracts import CATEGORY_TITLE_MAX_LENGTH
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


#: Single grapheme clusters, including the awkward shapes: a ZWJ family, a
#: skin tone, a keycap, a flag and a letter with a combining accent.
GRAPHEME_CLUSTERS: tuple[str, ...] = (
    "\U0001f48a",
    "\U0001f4a7",
    "\U0001f3c3",
    "\U0001f44d\U0001f3fd",
    "\U0001f468‍\U0001f469‍\U0001f467",
    "\U0001f1f7\U0001f1fa",
    "1️⃣",
    "é",
)

emoji_clusters = st.sampled_from(GRAPHEME_CLUSTERS)

#: Anything a user may type as a title, collapsed the way the domain does it.
category_titles = (
    st.text(min_size=1, max_size=CATEGORY_TITLE_MAX_LENGTH)
    .map(lambda value: " ".join(value.split()))
    .filter(lambda value: 1 <= len(value) <= CATEGORY_TITLE_MAX_LENGTH)
)
