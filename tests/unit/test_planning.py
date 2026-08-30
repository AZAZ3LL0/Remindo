"""Invariants of the planner window (tech.md 7.1, 10).

Acceptance criteria this file encodes: the horizon never reaches past a
boundary, no moment inside the horizon is ever skipped, and a reminder is
called exhausted only when nothing can follow.
"""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from app.domain.planning import (
    MAX_OCCURRENCES_PER_CYCLE,
    PlanBounds,
    last_moment_of,
    plan_window,
    settle_plan,
)
from app.domain.recurrence import next_occurrences, to_utc
from app.domain.reminders import BOUNDARY
from app.domain.schedules import DailySchedule, IntervalSchedule, OnceSchedule
from tests.unit.strategies import schedules, timezones, utc_moments

CASES = settings(max_examples=60, deadline=None)

horizons = st.integers(min_value=1, max_value=24 * 30)
counts = st.integers(min_value=0, max_value=50)
budgets = st.one_of(st.none(), st.integers(min_value=1, max_value=50))


@st.composite
def bounds_and_horizon(draw: st.DrawFn) -> tuple[PlanBounds, datetime]:
    """A reminder's boundaries together with the horizon of one cycle."""
    starts_at = draw(utc_moments)
    planned_until = draw(
        st.one_of(
            st.none(),
            st.integers(min_value=0, max_value=60 * 24 * 10).map(
                lambda minutes: starts_at + timedelta(minutes=minutes)
            ),
        )
    )
    ends_at = draw(
        st.one_of(
            st.none(),
            st.integers(min_value=1, max_value=60 * 24 * 30).map(
                lambda minutes: starts_at + timedelta(minutes=minutes)
            ),
        )
    )
    last_moment = draw(
        st.one_of(
            st.none(),
            st.integers(min_value=-60 * 24, max_value=60 * 24 * 30).map(
                lambda minutes: starts_at + timedelta(minutes=minutes)
            ),
        )
    )
    bounds = PlanBounds(
        starts_at=starts_at,
        planned_until=planned_until,
        ends_at=ends_at,
        max_occurrences=draw(budgets),
        last_moment=last_moment,
    )
    horizon_end = starts_at + timedelta(hours=draw(horizons))
    return bounds, horizon_end


@CASES
@given(case=bounds_and_horizon(), fired_count=counts)
def test_window_never_reaches_past_a_boundary(case, fired_count):
    bounds, horizon_end = case

    window = plan_window(bounds, horizon_end=horizon_end, fired_count=fired_count)

    assert window.until <= horizon_end
    if bounds.ends_at is not None:
        assert window.until <= bounds.ends_at
    assert window.after >= bounds.starts_at - BOUNDARY
    if bounds.planned_until is not None:
        assert window.after >= bounds.planned_until


@CASES
@given(case=bounds_and_horizon(), fired_count=counts)
def test_budget_caps_the_limit(case, fired_count):
    bounds, horizon_end = case

    window = plan_window(bounds, horizon_end=horizon_end, fired_count=fired_count)

    assert 0 <= window.limit <= MAX_OCCURRENCES_PER_CYCLE
    if bounds.max_occurrences is not None:
        assert window.limit <= max(bounds.max_occurrences - fired_count, 0)


@CASES
@given(case=bounds_and_horizon(), fired_count=counts)
def test_a_spent_budget_leaves_nothing_to_plan(case, fired_count):
    """Once the budget is gone the window is empty, not merely small."""
    bounds, horizon_end = case
    assume(bounds.max_occurrences is not None)

    window = plan_window(
        bounds, horizon_end=horizon_end, fired_count=fired_count + bounds.max_occurrences
    )

    assert window.is_empty


@CASES
@given(case=bounds_and_horizon(), fired_count=counts)
def test_planning_is_deterministic(case, fired_count):
    bounds, horizon_end = case
    first = plan_window(bounds, horizon_end=horizon_end, fired_count=fired_count)
    second = plan_window(bounds, horizon_end=horizon_end, fired_count=fired_count)
    assert first == second


@CASES
@given(schedule=schedules, tz=timezones, case=bounds_and_horizon())
def test_the_horizon_only_moves_forward(schedule, tz, case):
    """`planned_until` is a watermark: a cycle never rewinds it."""
    bounds, horizon_end = case
    window = plan_window(bounds, horizon_end=horizon_end, fired_count=0)
    moments = (
        []
        if window.is_empty
        else next_occurrences(
            schedule, tz, after=window.after, until=window.until, limit=window.limit
        )
    )

    outcome = settle_plan(bounds, window, moments, fired_count=len(moments))

    assert outcome.planned_until >= window.after
    assert outcome.planned_until <= max(window.after, window.until)
    if bounds.planned_until is not None:
        assert outcome.planned_until >= bounds.planned_until


@CASES
@given(schedule=schedules, tz=timezones, case=bounds_and_horizon(), batch_limit=st.integers(1, 6))
def test_a_truncated_cycle_loses_no_moment(schedule, tz, case, batch_limit):
    """What the limit cut off stays inside the next cycle's window."""
    bounds, horizon_end = case
    window = plan_window(bounds, horizon_end=horizon_end, fired_count=0, batch_limit=batch_limit)
    assume(not window.is_empty)
    moments = next_occurrences(
        schedule, tz, after=window.after, until=window.until, limit=window.limit
    )
    assume(len(moments) == window.limit)

    outcome = settle_plan(bounds, window, moments, fired_count=len(moments))
    resumed = plan_window(
        PlanBounds(
            starts_at=bounds.starts_at,
            planned_until=outcome.planned_until,
            ends_at=bounds.ends_at,
            max_occurrences=None,
            last_moment=bounds.last_moment,
        ),
        horizon_end=horizon_end,
        fired_count=0,
    )
    dropped = next_occurrences(
        schedule, tz, after=window.after, until=window.until, limit=window.limit + 20
    )[window.limit :]

    assert outcome.planned_until == moments[-1]
    assert all(resumed.after < moment <= resumed.until for moment in dropped)


@CASES
@given(schedule=schedules, tz=timezones)
def test_only_a_one_shot_schedule_ends_on_its_own(schedule, tz):
    last = last_moment_of(schedule, tz)
    if isinstance(schedule, OnceSchedule):
        assert last == to_utc(schedule.at, tz)
    else:
        assert last is None


def test_a_recurring_reminder_without_bounds_is_never_exhausted():
    starts_at = datetime(2026, 6, 1, 12, tzinfo=UTC)
    bounds = PlanBounds(starts_at=starts_at)
    window = plan_window(bounds, horizon_end=starts_at + timedelta(hours=48), fired_count=0)

    outcome = settle_plan(bounds, window, [starts_at + timedelta(hours=1)], fired_count=1)

    assert outcome.planned_until == starts_at + timedelta(hours=48)
    assert outcome.exhausted is False


@pytest.mark.parametrize(
    ("ends_at_hours", "max_occurrences", "fired_count", "expected"),
    [
        (None, None, 99, False),
        (24, None, 1, True),
        (None, 3, 3, True),
        (None, 3, 2, False),
    ],
)
def test_exhaustion_reasons(ends_at_hours, max_occurrences, fired_count, expected):
    starts_at = datetime(2026, 6, 1, 12, tzinfo=UTC)
    bounds = PlanBounds(
        starts_at=starts_at,
        ends_at=None if ends_at_hours is None else starts_at + timedelta(hours=ends_at_hours),
        max_occurrences=max_occurrences,
    )
    window = plan_window(bounds, horizon_end=starts_at + timedelta(hours=48), fired_count=0)

    outcome = settle_plan(bounds, window, [], fired_count=fired_count)

    assert outcome.exhausted is expected


def test_a_one_shot_moment_left_behind_exhausts_the_reminder():
    """The minute has passed, so no cycle will ever materialise it again."""
    starts_at = datetime(2026, 6, 1, 12, tzinfo=UTC)
    schedule = OnceSchedule(at="2026-05-30T08:00")
    bounds = PlanBounds(starts_at=starts_at, last_moment=last_moment_of(schedule, ZoneInfo("UTC")))
    window = plan_window(bounds, horizon_end=starts_at + timedelta(hours=48), fired_count=0)

    outcome = settle_plan(bounds, window, [], fired_count=0)

    assert outcome.exhausted is True


def test_a_dense_schedule_is_cut_at_the_batch_limit():
    starts_at = datetime(2026, 6, 1, 12, tzinfo=UTC)
    schedule = IntervalSchedule(every_minutes=5, window_start="00:00", window_end="23:55")
    bounds = PlanBounds(starts_at=starts_at)
    window = plan_window(bounds, horizon_end=starts_at + timedelta(hours=48), fired_count=0)
    moments = next_occurrences(
        schedule, ZoneInfo("UTC"), after=window.after, until=window.until, limit=window.limit
    )

    outcome = settle_plan(bounds, window, moments, fired_count=len(moments))

    assert len(moments) == MAX_OCCURRENCES_PER_CYCLE
    assert outcome.planned_until == moments[-1]
    assert outcome.planned_until < window.until


def test_a_daily_schedule_fits_the_horizon_whole():
    starts_at = datetime(2026, 6, 1, 12, tzinfo=UTC)
    schedule = DailySchedule(times=["08:00", "20:00"])
    bounds = PlanBounds(starts_at=starts_at)
    window = plan_window(bounds, horizon_end=starts_at + timedelta(hours=48), fired_count=0)
    moments = next_occurrences(
        schedule, ZoneInfo("UTC"), after=window.after, until=window.until, limit=window.limit
    )

    outcome = settle_plan(bounds, window, moments, fired_count=len(moments))

    assert outcome.planned_until == window.until
