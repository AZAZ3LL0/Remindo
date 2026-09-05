"""Invariants of next_occurrences (tech.md 10, 19.6).

Transition dates come from `zoneinfo` through `tests/unit/dst.py`, so the
rules below stay true when tzdata ships a new release.
"""

import calendar
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from zoneinfo import ZoneInfo

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from app.domain.recurrence import next_occurrences, to_utc
from app.domain.reminders import BOUNDARY
from app.domain.schedules import (
    DailySchedule,
    IntervalSchedule,
    WeeklySchedule,
    parse_hhmm,
    parse_schedule,
)
from tests.unit.dst import (
    ambiguous_local_time,
    is_nonexistent,
    local_naive,
    nonexistent_local_time,
    transitions,
)
from tests.unit.strategies import (
    DST_TIMEZONE_NAMES,
    daily_schedules,
    dst_timezones,
    hhmm,
    local_dates,
    monthly_last_day_schedules,
    monthly_skip_schedules,
    ranges,
    schedules,
    timezones,
    wall_clock_schedules,
    weekly_schedules,
)

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


#: A ceiling the split can never reach. Six days hold at most 1728 moments,
#: the tightest schedule being a five-minute interval across the whole day. A
#: limit that binds would truncate the whole range while the two halves keep
#: everything, and the concatenation below would be comparing different things.
SPLIT_LIMIT = 2000


@SLOW
@given(schedule=schedules, tz=timezones, window=ranges(max_days=6))
def test_range_splits_without_gaps_or_duplicates(schedule, tz, window):
    """(a, c] equals (a, b] concatenated with (b, c]."""
    after, until = window
    middle = after + (until - after) / 2
    middle = middle.replace(second=0, microsecond=0)

    whole = next_occurrences(schedule, tz, after=after, until=until, limit=SPLIT_LIMIT)
    first = next_occurrences(schedule, tz, after=after, until=middle, limit=SPLIT_LIMIT)
    second = next_occurrences(schedule, tz, after=middle, until=until, limit=SPLIT_LIMIT)

    # The invariant is about the range, not about the ceiling: a truncated list
    # would make the assertion below pass or fail for the wrong reason.
    assert len(whole) < SPLIT_LIMIT
    assert whole == first + second


@SLOW
@given(schedule=wall_clock_schedules, tz=timezones, window=ranges(max_days=10))
def test_wall_clock_time_survives(schedule, tz, window):
    """Rules 1 and 3: 07:30 stays 07:30 unless 07:30 did not happen that day.

    A day carrying a transition is the interesting day, so it is not skipped.
    The only local time a moment may show outside `times` is one the wizard
    asked for, that the clock jumped over, and that therefore moved forward.
    """
    after, until = window
    for moment in next_occurrences(schedule, tz, after=after, until=until, limit=100):
        local = moment.astimezone(tz)
        if local.time() in schedule.times:
            continue
        assert any(
            wanted < local.time() and is_nonexistent(datetime.combine(local.date(), wanted), tz)
            for wanted in schedule.times
        ), f"{local} matches no time in {schedule.times}"


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


@SLOW
@given(
    tz=timezones,
    every_minutes=st.integers(min_value=5, max_value=720),
    window=st.tuples(hhmm, hhmm),
    day=local_dates,
)
def test_interval_spacing_is_absolute_inside_one_window(tz, every_minutes, window, day):
    """Rule 2, stated exactly: inside one window the step never bends.

    The range is the window itself, so nothing from a neighbouring window can
    creep in and make a shorter gap look legal. A window carrying a transition
    is the interesting case, which is why the day is drawn freely.
    """
    window_start, window_end = window
    schedule = IntervalSchedule(
        every_minutes=every_minutes, window_start=window_start, window_end=window_end
    )
    start = to_utc(datetime.combine(day, parse_hhmm(window_start)), tz)
    end_day = day if parse_hhmm(window_end) > parse_hhmm(window_start) else day + timedelta(days=1)
    end = to_utc(datetime.combine(end_day, parse_hhmm(window_end)), tz)
    if end <= start:
        return

    result = next_occurrences(
        schedule, tz, after=start - BOUNDARY, until=end - BOUNDARY, limit=1000
    )

    assert result, "a window wider than the step fires at least once"
    assert result[0] == start
    for previous, current in pairwise(result):
        assert current - previous == timedelta(minutes=every_minutes)


@SLOW
@given(schedule=weekly_schedules, tz=timezones, window=ranges(max_days=14))
def test_weekly_fires_only_on_chosen_weekdays_locally(schedule, tz, window):
    """The weekday is the user's weekday. In UTC it is often a different day."""
    after, until = window
    for moment in next_occurrences(schedule, tz, after=after, until=until, limit=100):
        assert moment.astimezone(tz).isoweekday() in schedule.weekdays


@SLOW
@given(schedule=monthly_skip_schedules, tz=timezones, window=ranges(max_days=14))
def test_monthly_skip_never_invents_a_day(schedule, tz, window):
    """`skip` means the month is dropped, not moved onto a neighbouring day."""
    after, until = window
    for moment in next_occurrences(schedule, tz, after=after, until=until, limit=100):
        assert moment.astimezone(tz).day in schedule.days


@SLOW
@given(schedule=monthly_last_day_schedules, tz=timezones, window=ranges(max_days=14))
def test_monthly_last_day_only_falls_back_to_the_end_of_the_month(schedule, tz, window):
    """`last_day` moves a missing day to the month's end and nowhere else."""
    after, until = window
    for moment in next_occurrences(schedule, tz, after=after, until=until, limit=100):
        local = moment.astimezone(tz)
        last = calendar.monthrange(local.year, local.month)[1]
        assert local.day in schedule.days or local.day == last


@SLOW
@given(schedule=daily_schedules, tz=timezones, window=ranges(max_days=21))
def test_daily_keeps_its_stride_in_days(schedule, tz, window):
    """`every_n_days` counts local days, so a DST day still counts as one."""
    after, until = window
    dates = sorted(
        {
            moment.astimezone(tz).date()
            for moment in next_occurrences(schedule, tz, after=after, until=until, limit=200)
        }
    )
    for previous, current in pairwise(dates):
        assert (current - previous).days % schedule.every_n_days == 0


def dst_cases(pick):
    """Every transition of every shifting zone that `pick` finds a moment in."""
    cases = []
    for name in DST_TIMEZONE_NAMES:
        tz = ZoneInfo(name)
        for transition in transitions(tz):
            naive = pick(transition, tz)
            if naive is not None:
                cases.append(pytest.param(tz, transition, naive, id=f"{name}@{transition.date()}"))
    return cases


@pytest.mark.parametrize(("tz", "transition", "naive"), dst_cases(nonexistent_local_time))
def test_rule_three_holds_at_every_spring_forward(tz, transition, naive):
    """A time the clock skipped becomes the first moment that does exist.

    Not merely "some later moment": one second earlier the local clock had not
    reached `naive` yet, so nothing between the two was passed over.
    """
    resolved = to_utc(naive, tz)

    assert local_naive(resolved, tz) > naive
    assert local_naive(resolved - timedelta(seconds=1), tz) < naive
    assert resolved == transition


@pytest.mark.parametrize(("tz", "transition", "naive"), dst_cases(ambiguous_local_time))
def test_rule_four_holds_at_every_fall_back(tz, transition, naive):
    """A time the clock passed twice resolves to the first of the two."""
    early = naive.replace(tzinfo=tz, fold=0).astimezone(UTC)
    late = naive.replace(tzinfo=tz, fold=1).astimezone(UTC)

    assert early < transition <= late, "the sample really is ambiguous"

    resolved = to_utc(naive, tz)

    assert resolved == min(early, late)
    assert local_naive(resolved, tz) == naive


def transition_cases():
    """Every transition of every shifting zone, whichever way the clock moved."""
    cases = []
    for name in DST_TIMEZONE_NAMES:
        tz = ZoneInfo(name)
        for transition in transitions(tz):
            cases.append(pytest.param(tz, transition, id=f"{name}@{transition.date()}"))
    return cases


@pytest.mark.parametrize(("tz", "transition"), transition_cases())
@pytest.mark.parametrize("every_minutes", [30, 60, 90])
def test_interval_keeps_absolute_spacing_across_every_transition(every_minutes, tz, transition):
    """Rule 2 on the only days where it can be broken.

    The property test above draws a day at random and almost never lands on a
    transition, so the rule is also checked on each transition by name. A
    schedule stepping wall-clock time instead of absolute time survives the
    former and fails here.
    """
    schedule = IntervalSchedule(
        every_minutes=every_minutes, window_start="00:00", window_end="00:00"
    )
    day = local_naive(transition, tz).date()
    start = to_utc(datetime.combine(day, datetime.min.time()), tz)
    end = to_utc(datetime.combine(day + timedelta(days=1), datetime.min.time()), tz)

    assert start < transition < end, "the sample day really carries the transition"
    assert end - start != timedelta(days=1), "and the day really is longer or shorter"

    result = next_occurrences(schedule, tz, after=start - BOUNDARY, until=end - BOUNDARY, limit=200)

    assert result[0] == start
    for previous, current in pairwise(result):
        assert current - previous == timedelta(minutes=every_minutes)


@SLOW
@given(schedule=wall_clock_schedules, tz=dst_timezones)
def test_a_wall_clock_schedule_survives_every_transition(schedule, tz):
    """Every transition of the zone is crossed, not only the one a range hit."""
    for transition in transitions(tz):
        result = next_occurrences(
            schedule,
            tz,
            after=transition - timedelta(days=2),
            until=transition + timedelta(days=2),
            limit=200,
        )
        assert result == sorted(set(result))
        for moment in result:
            local = moment.astimezone(tz)
            assert local.time() in schedule.times or any(
                wanted < local.time() and is_nonexistent(datetime.combine(local.date(), wanted), tz)
                for wanted in schedule.times
            )
