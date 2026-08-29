"""Acceptance rules of personal settings, checked as properties.

The criteria come from tech.md 1.1, 4.2 and 16.6: a user lives in an IANA zone,
reads ru or en, and quiet hours are set and cleared together and actually
silence something.
"""

from datetime import time
from zoneinfo import ZoneInfo, available_timezones

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from app.domain.contracts import POPULAR_TIMEZONES, Language
from app.domain.errors import ValidationError
from app.domain.onboarding import (
    MAX_TIMEZONE_LENGTH,
    normalize_language,
    normalize_quiet_hours,
    normalize_timezone,
    parse_wall_time,
)
from app.domain.quiet_hours import apply_quiet_hours, is_quiet
from app.domain.schedules import format_hhmm
from tests.unit.strategies import hhmm, local_times, timezones, utc_moments

CASES = settings(max_examples=200, deadline=None)

#: Names short enough for the column, drawn from the running tzdata.
installed_zones = st.sampled_from(
    sorted(name for name in available_timezones() if len(name) <= MAX_TIMEZONE_LENGTH)
)


class TestLanguage:
    @given(code=st.sampled_from([code.value for code in Language]))
    def test_every_supported_code_is_accepted(self, code):
        assert normalize_language(code) == Language(code)

    @given(code=st.sampled_from([code.value for code in Language]), pad=st.sampled_from(" \t\n"))
    def test_surrounding_whitespace_and_case_do_not_matter(self, code, pad):
        assert normalize_language(f"{pad}{code.upper()}{pad}") == Language(code)

    @CASES
    @given(raw=st.text(max_size=12))
    def test_anything_else_is_rejected(self, raw):
        assume(raw.strip().lower() not in {code.value for code in Language})

        with pytest.raises(ValidationError):
            normalize_language(raw)


class TestTimezone:
    @given(name=installed_zones)
    def test_every_installed_zone_resolves_and_is_returned_verbatim(self, name):
        assert normalize_timezone(name) == name
        assert ZoneInfo(normalize_timezone(name))

    @given(name=installed_zones)
    def test_normalizing_twice_changes_nothing(self, name):
        assert normalize_timezone(normalize_timezone(name)) == normalize_timezone(name)

    @pytest.mark.parametrize("name", POPULAR_TIMEZONES)
    def test_every_offered_zone_passes_its_own_validation(self, name):
        assert normalize_timezone(name) == name

    @pytest.mark.parametrize(
        "raw",
        ["", "   ", "Mars/Olympus", "Europe", "../etc/passwd", "europe/moscow", "x" * 200],
    )
    def test_junk_is_rejected(self, raw):
        with pytest.raises(ValidationError):
            normalize_timezone(raw)


class TestWallTime:
    @given(value=local_times)
    def test_formatting_and_parsing_are_inverse(self, value):
        assert parse_wall_time(format_hhmm(value)) == value

    @given(text=hhmm, pad=st.sampled_from(["", " ", "  "]))
    def test_surrounding_whitespace_is_tolerated(self, text, pad):
        assert parse_wall_time(f"{pad}{text}{pad}") == parse_wall_time(text)

    @CASES
    @given(raw=st.text(max_size=8))
    def test_anything_that_is_not_hh_mm_is_rejected(self, raw):
        try:
            parsed = parse_wall_time(raw)
        except ValidationError:
            return
        assert format_hhmm(parsed) == raw.strip()

    @pytest.mark.parametrize("raw", ["25:00", "12:60", "7:00", "0700", "12:00:00", "noon", ""])
    def test_known_bad_shapes_are_rejected(self, raw):
        with pytest.raises(ValidationError):
            parse_wall_time(raw)


class TestQuietHours:
    def test_absent_bounds_mean_quiet_hours_are_off(self):
        assert normalize_quiet_hours(None, None) is None

    @given(bound=local_times)
    def test_one_bound_alone_is_rejected(self, bound):
        """The column carries a CHECK for exactly this (tech.md 4.2)."""
        with pytest.raises(ValidationError):
            normalize_quiet_hours(bound, None)
        with pytest.raises(ValidationError):
            normalize_quiet_hours(None, bound)

    @given(bound=local_times)
    def test_equal_bounds_are_rejected(self, bound):
        with pytest.raises(ValidationError):
            normalize_quiet_hours(bound, bound)

    @given(start=local_times, end=local_times)
    def test_distinct_bounds_pass_through_unchanged(self, start, end):
        assume(start != end)

        assert normalize_quiet_hours(start, end) == (start, end)

    @given(start=local_times, end=local_times)
    def test_normalizing_twice_changes_nothing(self, start, end):
        assume(start != end)
        once = normalize_quiet_hours(start, end)

        assert normalize_quiet_hours(*once) == once

    @given(start=local_times, end=local_times)
    def test_crossing_midnight_is_allowed(self, start, end):
        """`quiet_start > quiet_end` is a night interval, not an error."""
        assume(start > end)

        assert normalize_quiet_hours(start, end) == (start, end)

    @given(bound=local_times, seconds=st.integers(min_value=1, max_value=59))
    def test_sub_minute_precision_is_rejected(self, bound, seconds):
        with pytest.raises(ValidationError):
            normalize_quiet_hours(bound.replace(second=seconds), time(0, 0))

    @CASES
    @given(start=local_times, end=local_times, tz=timezones, moment=utc_moments)
    def test_an_accepted_interval_can_actually_silence_something(self, start, end, tz, moment):
        """An interval the user may save is one `apply_quiet_hours` reacts to.

        Equal bounds are rejected precisely because they silence nothing; the
        accepted ones must keep the promise from tech.md 1.1.
        """
        assume(start != end)
        interval = normalize_quiet_hours(start, end)
        assert interval is not None

        assert is_quiet(start, *interval)
        assert not is_quiet(end, *interval)
        assert apply_quiet_hours(moment, tz, *interval) >= moment
