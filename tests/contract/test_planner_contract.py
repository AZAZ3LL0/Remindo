"""The seam the planner sits on (tech.md 7.1, 10).

Two contracts meet here. The wizard promises a first firing moment and the
planner must materialise that exact moment (tech.md 18.6), and archiving a
reminder must never throw away a firing that was still ahead of it.
"""

from datetime import timedelta

from hypothesis import given, settings
from hypothesis import strategies as st

from app.domain.planning import PlanBounds, last_moment_of, plan_window, settle_plan
from app.domain.recurrence import next_occurrences
from app.domain.reminders import first_fire_at
from app.domain.schedules import dump_schedule, parse_schedule
from tests.unit.strategies import once_schedules, schedules, timezones, utc_moments

CASES = settings(max_examples=60, deadline=None)

HORIZON = timedelta(hours=48)


def first_window(starts_at, horizon_end):
    return plan_window(PlanBounds(starts_at=starts_at), horizon_end=horizon_end, fired_count=0)


@CASES
@given(schedule=schedules, tz=timezones, starts_at=utc_moments)
def test_the_planner_and_the_wizard_agree_on_the_first_moment(schedule, tz, starts_at):
    """One boundary, two readers: the card and the queue agree or the card lies."""
    promised = first_fire_at(schedule, tz, starts_at)
    window = first_window(starts_at, starts_at + HORIZON)

    moments = next_occurrences(
        schedule, tz, after=window.after, until=window.until, limit=window.limit
    )

    if promised is not None and promised <= starts_at + HORIZON:
        assert moments[:1] == [promised]
    else:
        assert moments == []


@CASES
@given(schedule=once_schedules, tz=timezones, days=st.integers(1, 400))
def test_archiving_never_drops_a_firing_still_ahead(schedule, tz, days):
    """`last_moment_of` is an upper bound, so exhaustion is never premature.

    Only a `once` schedule claims a bound; the recurring kinds return `None`
    and are never archived on this reason at all.
    """
    last = last_moment_of(schedule, tz)
    assert last is not None

    beyond = next_occurrences(schedule, tz, after=last, until=last + timedelta(days=days), limit=5)

    assert beyond == []


@CASES
@given(schedule=schedules, tz=timezones, starts_at=utc_moments)
def test_consecutive_cycles_cover_the_horizon_exactly_once(schedule, tz, starts_at):
    """The watermark is the idempotency key of the cycle, not just a bookmark."""
    horizon_end = starts_at + HORIZON
    bounds = PlanBounds(starts_at=starts_at)
    first = first_window(starts_at, starts_at + HORIZON / 2)
    early = next_occurrences(schedule, tz, after=first.after, until=first.until, limit=first.limit)
    outcome = settle_plan(bounds, first, early, fired_count=len(early))

    second = plan_window(
        PlanBounds(starts_at=starts_at, planned_until=outcome.planned_until),
        horizon_end=horizon_end,
        fired_count=len(early),
    )
    late = next_occurrences(
        schedule, tz, after=second.after, until=second.until, limit=second.limit
    )
    whole = next_occurrences(
        schedule,
        tz,
        after=first.after,
        until=horizon_end,
        limit=first.limit + second.limit,
    )

    assert set(early) & set(late) == set()
    assert early + late == whole


@CASES
@given(schedule=schedules, tz=timezones, starts_at=utc_moments)
def test_the_planner_reads_back_what_the_wizard_stored(schedule, tz, starts_at):
    """The planner expands the JSONB payload, never the object that wrote it."""
    stored = dump_schedule(schedule)
    window = first_window(starts_at, starts_at + HORIZON)

    from_object = next_occurrences(
        schedule, tz, after=window.after, until=window.until, limit=window.limit
    )
    from_payload = next_occurrences(
        parse_schedule(stored), tz, after=window.after, until=window.until, limit=window.limit
    )

    assert from_payload == from_object
