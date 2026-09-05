"""The weekly moment and the window it covers (tech.md 23.8).

The invariants are read off the contract, not off the implementation: the
digest must arrive on the right local weekday, at most once per local week,
and its window must abut the previous one exactly, including across the DST
transitions the schedules already have to survive.
"""

from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.domain.digest import DAYS_IN_WEEK, digest_due_at, digest_window, last_digest_moment
from app.domain.quiet_hours import QuietHours
from tests.unit.dst import is_nonexistent, local_naive, transitions
from tests.unit.strategies import dst_timezones, quiet_hours, timezones, utc_moments

CASES = settings(max_examples=200, deadline=None)

weekdays = st.integers(min_value=1, max_value=7)
hours = st.integers(min_value=0, max_value=23)

MICROSECOND = timedelta(microseconds=1)


def _due(now, tz, weekday=1, hour=9, sent_at=None, quiet=None):
    return digest_due_at(
        now,
        tz,
        weekday=weekday,
        hour=hour,
        sent_at=sent_at,
        quiet=quiet if quiet is not None else QuietHours(tz=tz),
    )


@CASES
@given(now=utc_moments, tz=timezones, weekday=weekdays, hour=hours)
def test_the_moment_is_never_in_the_future(now, tz, weekday, hour):
    assert last_digest_moment(now, tz, weekday, hour) <= now


@CASES
@given(now=utc_moments, tz=timezones, weekday=weekdays, hour=hours)
def test_the_moment_lands_on_the_configured_local_weekday(now, tz, weekday, hour):
    moment = last_digest_moment(now, tz, weekday, hour)
    assert moment.astimezone(tz).date().isoweekday() == weekday


@CASES
@given(now=utc_moments, tz=timezones, weekday=weekdays, hour=hours)
def test_the_moment_keeps_its_local_hour_unless_that_hour_is_missing(now, tz, weekday, hour):
    """Rule 1: the wall clock wins, and a nonexistent hour moves forward."""
    moment = last_digest_moment(now, tz, weekday, hour)
    local = moment.astimezone(tz)
    if local.hour != hour:
        wanted = datetime.combine(local.date(), local.time().replace(hour=hour, minute=0))
        assert is_nonexistent(wanted, tz)
        assert local_naive(moment, tz) > wanted


@CASES
@given(now=utc_moments, tz=timezones, weekday=weekdays, hour=hours)
def test_the_moment_is_a_function_of_its_arguments(now, tz, weekday, hour):
    assert last_digest_moment(now, tz, weekday, hour) == last_digest_moment(now, tz, weekday, hour)


@CASES
@given(now=utc_moments, tz=timezones, weekday=weekdays, hour=hours)
def test_consecutive_moments_are_one_local_week_apart(now, tz, weekday, hour):
    """Rule 2: a week is seven local days, not one hundred and sixty-eight hours.

    A DST transition inside the week makes the gap an hour shorter or longer,
    and that is the point: the digest keeps its local hour the way a daily
    schedule keeps its local time.
    """
    moment = last_digest_moment(now, tz, weekday, hour)
    previous = last_digest_moment(moment - MICROSECOND, tz, weekday, hour)

    assert previous < moment
    assert abs((moment - previous) - timedelta(days=DAYS_IN_WEEK)) <= timedelta(hours=1)
    assert previous.astimezone(tz).date().isoweekday() == weekday


@CASES
@given(now=utc_moments, tz=timezones, weekday=weekdays, hour=hours)
def test_windows_of_adjacent_weeks_abut_exactly(now, tz, weekday, hour):
    """Rule 3: no gap and no overlap, the way local days stack in /today."""
    moment = last_digest_moment(now, tz, weekday, hour)
    previous = last_digest_moment(moment - MICROSECOND, tz, weekday, hour)

    window = digest_window(moment, tz)
    earlier = digest_window(previous, tz)

    assert window.end == moment
    assert window.start == previous
    assert earlier.end == window.start


@CASES
@given(now=utc_moments, tz=dst_timezones, weekday=weekdays, hour=hours)
def test_a_window_covers_seven_local_days(now, tz, weekday, hour):
    """Seven days on the wall clock, unless that wall time never happened."""
    moment = last_digest_moment(now, tz, weekday, hour)
    window = digest_window(moment, tz)
    wanted = local_naive(window.end, tz) - timedelta(days=DAYS_IN_WEEK)

    if is_nonexistent(wanted, tz):
        assert local_naive(window.start, tz) > wanted
    else:
        assert local_naive(window.start, tz) == wanted


@CASES
@given(now=utc_moments, tz=timezones, weekday=weekdays, hour=hours, quiet=quiet_hours)
def test_a_due_digest_is_always_the_unshifted_weekly_moment(now, tz, weekday, hour, quiet):
    """Rule 4: quiet hours delay the send and never rename the week."""
    moment = _due(now, tz, weekday, hour, quiet=quiet)
    if moment is not None:
        assert moment == last_digest_moment(now, tz, weekday, hour)


@CASES
@given(now=utc_moments, tz=timezones, weekday=weekdays, hour=hours, quiet=quiet_hours)
def test_a_marked_week_is_never_owed_again(now, tz, weekday, hour, quiet):
    """The mark is the idempotency key: replaying the cycle owes nothing."""
    moment = _due(now, tz, weekday, hour, quiet=quiet)
    if moment is None:
        return
    assert _due(now, tz, weekday, hour, sent_at=moment, quiet=quiet) is None


@CASES
@given(now=utc_moments, tz=timezones, weekday=weekdays, hour=hours, quiet=quiet_hours)
def test_silence_only_ever_postpones(now, tz, weekday, hour, quiet):
    """A digest owed under silence is owed without it, never the other way."""
    silenced = _due(now, tz, weekday, hour, quiet=quiet)
    if silenced is not None:
        assert _due(now, tz, weekday, hour) == silenced


@CASES
@given(now=utc_moments, tz=timezones, weekday=weekdays, hour=hours)
def test_a_mark_from_an_older_week_still_owes_the_current_one(now, tz, weekday, hour):
    moment = last_digest_moment(now, tz, weekday, hour)
    older = last_digest_moment(moment - MICROSECOND, tz, weekday, hour)
    assert _due(now, tz, weekday, hour, sent_at=older) == moment


def test_a_digest_is_owed_the_moment_its_hour_arrives():
    tz = ZoneInfo("Europe/Moscow")
    monday_nine = datetime(2026, 6, 1, 6, 0, tzinfo=UTC)  # 09:00 Moscow, a Monday

    assert _due(monday_nine - MICROSECOND, tz) != monday_nine
    assert _due(monday_nine, tz) == monday_nine


def test_silence_holds_the_digest_until_it_ends():
    """A user silent until noon reads the digest at noon, not at nine."""
    tz = ZoneInfo("Europe/Moscow")
    quiet = QuietHours(tz=tz, start=time(8, 0), end=time(12, 0))
    monday_nine = datetime(2026, 6, 1, 6, 0, tzinfo=UTC)

    assert _due(monday_nine, tz, quiet=quiet) is None
    assert _due(monday_nine + timedelta(hours=3), tz, quiet=quiet) == monday_nine


def test_a_new_user_is_owed_the_week_that_just_ended():
    """A null mark is not an overdue digest: it is simply the first one."""
    tz = ZoneInfo("Europe/Moscow")
    thursday = datetime(2026, 6, 4, 12, 0, tzinfo=UTC)
    assert _due(thursday, tz, sent_at=None) == datetime(2026, 6, 1, 6, 0, tzinfo=UTC)


@pytest.mark.parametrize("zone", ["Europe/Berlin", "America/New_York", "Australia/Lord_Howe"])
def test_the_week_across_a_transition_keeps_the_local_hour(zone):
    """Both windows around a real transition still start and end at 09:00."""
    tz = ZoneInfo(zone)
    for transition in transitions(tz):
        after = transition + timedelta(days=8)
        moment = last_digest_moment(after, tz, 1, 9)
        window = digest_window(moment, tz)
        assert local_naive(window.start, tz).hour == 9
        assert local_naive(window.end, tz).hour == 9


def test_now_must_be_aware():
    with pytest.raises(ValueError):
        last_digest_moment(datetime(2026, 6, 1, 12, 0), ZoneInfo("UTC"), 1, 9)
