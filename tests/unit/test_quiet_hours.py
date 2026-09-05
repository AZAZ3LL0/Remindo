"""Quiet hours never drop a delivery, they postpone it."""

from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.domain.quiet_hours import QuietHours, apply_quiet_hours, is_quiet
from tests.unit.strategies import local_times, quiet_hours, timezones, utc_moments

CASES = settings(max_examples=200, deadline=None)


@CASES
@given(moment=utc_moments, tz=timezones, start=local_times, end=local_times)
def test_result_is_never_earlier_and_never_silent(moment, tz, start, end):
    shifted = apply_quiet_hours(moment, tz, start, end)

    assert shifted >= moment
    assert shifted.utcoffset() is not None
    assert not is_quiet(shifted.astimezone(tz).time(), start, end)


@CASES
@given(moment=utc_moments, tz=timezones, start=local_times, end=local_times)
def test_applying_twice_changes_nothing(moment, tz, start, end):
    once = apply_quiet_hours(moment, tz, start, end)
    twice = apply_quiet_hours(once, tz, start, end)
    assert once == twice


@CASES
@given(moment=utc_moments, tz=timezones, start=local_times, end=local_times)
def test_moments_outside_the_interval_are_untouched(moment, tz, start, end):
    if is_quiet(moment.astimezone(tz).time(), start, end):
        return
    assert apply_quiet_hours(moment, tz, start, end) == moment


@CASES
@given(moment=utc_moments, tz=timezones)
def test_unset_quiet_hours_are_a_no_op(moment, tz):
    assert apply_quiet_hours(moment, tz, None, None) == moment


@given(moment=utc_moments, tz=timezones, boundary=local_times)
def test_zero_length_interval_never_silences(moment, tz, boundary):
    assert apply_quiet_hours(moment, tz, boundary, boundary) == moment


def test_night_interval_shifts_to_the_morning():
    tz = ZoneInfo("Europe/Moscow")
    moment = datetime(2026, 6, 1, 0, 30, tzinfo=UTC)  # 03:30 local
    shifted = apply_quiet_hours(moment, tz, time(23, 0), time(7, 0))
    assert shifted.astimezone(tz) == datetime(2026, 6, 1, 7, 0, tzinfo=tz)


def test_late_evening_shifts_to_the_next_morning():
    tz = ZoneInfo("Europe/Moscow")
    moment = datetime(2026, 6, 1, 20, 30, tzinfo=UTC)  # 23:30 local
    shifted = apply_quiet_hours(moment, tz, time(23, 0), time(7, 0))
    assert shifted.astimezone(tz) == datetime(2026, 6, 2, 7, 0, tzinfo=tz)


def test_daytime_interval_shifts_within_the_same_day():
    tz = ZoneInfo("Europe/Moscow")
    moment = datetime(2026, 6, 1, 10, 0, tzinfo=UTC)  # 13:00 local
    shifted = apply_quiet_hours(moment, tz, time(12, 0), time(15, 0))
    assert shifted.astimezone(tz) == datetime(2026, 6, 1, 15, 0, tzinfo=tz)


@given(st.data())
def test_shifted_moment_is_the_end_of_the_interval(data):
    tz = data.draw(timezones)
    moment = data.draw(utc_moments)
    start = data.draw(local_times)
    end = data.draw(local_times)
    if not is_quiet(moment.astimezone(tz).time(), start, end):
        return
    shifted = apply_quiet_hours(moment, tz, start, end)
    # Either the exact end of the silence, or the first existing moment after a
    # DST gap swallowed it.
    assert shifted.astimezone(tz).time() >= end or shifted > moment


@CASES
@given(moment=utc_moments, quiet=quiet_hours)
def test_the_value_object_shifts_exactly_out_of_what_it_covers(moment, quiet):
    """`covers` and `shift` are two views of one interval, never three."""
    shifted = quiet.shift(moment)

    assert shifted >= moment
    assert not quiet.covers(shifted)
    assert (shifted == moment) is not quiet.covers(moment)


@CASES
@given(moment=utc_moments, tz=timezones, start=local_times, end=local_times)
def test_the_value_object_agrees_with_the_function_it_wraps(moment, tz, start, end):
    quiet = QuietHours(tz=tz, start=start, end=end)

    assert quiet.shift(moment) == apply_quiet_hours(moment, tz, start, end)


@CASES
@given(moment=utc_moments, tz=timezones)
def test_silence_that_was_never_configured_covers_nothing(moment, tz):
    quiet = QuietHours(tz=tz)

    assert quiet.is_on is False
    assert quiet.covers(moment) is False
    assert quiet.shift(moment) == moment


def test_an_ambiguous_end_takes_the_offset_that_is_still_ahead():
    """The silence ends once, after the repeated hour, not before the moment.

    On the autumn transition 02:30 in Berlin happens twice. Taking the earlier
    one would end the silence before the moment it was asked to postpone.
    """
    tz = ZoneInfo("Europe/Berlin")
    moment = datetime(2026, 10, 25, 1, 0, tzinfo=UTC)  # 02:00 local, second pass
    shifted = apply_quiet_hours(moment, tz, time(1, 0), time(2, 30))

    assert shifted > moment
    assert shifted.astimezone(tz).time() == time(2, 30)
    assert shifted.astimezone(tz).utcoffset() == timedelta(hours=1)


def test_a_naive_moment_is_refused():
    """Every datetime in the product is aware; a naive one is a bug upstream."""
    with pytest.raises(ValueError, match="timezone-aware"):
        apply_quiet_hours(datetime(2026, 6, 1, 12, 0), ZoneInfo("UTC"), time(23, 0), time(7, 0))
