"""Rules of the wizard draft (tech.md 18.6), stated as properties.

Acceptance criteria of tech.md 15 (S3): a title the user typed is stored the
way it reads, a date belongs to a window the wizard can schedule on, and a
reminder is only created when something is actually going to fire.
"""

from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from hypothesis import assume, given
from hypothesis import strategies as st

from app.domain.contracts import (
    REMINDER_TITLE_MAX_LENGTH,
    REPEAT_MAX_MINUTES,
    REPEAT_MIN_MINUTES,
    SNOOZE_MAX_MINUTES,
    SNOOZE_MIN_MINUTES,
    WIZARD_MAX_DAYS_AHEAD,
)
from app.domain.errors import ValidationError
from app.domain.recurrence import next_occurrences, to_utc
from app.domain.reminders import (
    BOUNDARY,
    build_daily_schedule,
    build_interval_schedule,
    build_monthly_schedule,
    build_once_schedule,
    build_weekly_schedule,
    first_fire_at,
    local_day_bounds,
    local_today,
    normalize_note,
    normalize_reminder_title,
    parse_user_date,
    parse_user_interval,
    parse_user_repeat,
    parse_user_snooze,
    parse_user_window,
)
from app.domain.schedules import (
    INTERVAL_MAX_MINUTES,
    INTERVAL_MIN_MINUTES,
    MONTH_DAYS_MAX_LENGTH,
    TIMES_MAX_LENGTH,
    format_hhmm,
    format_local_date,
)
from tests.unit.dst import transitions
from tests.unit.strategies import (
    DST_TIMEZONE_NAMES,
    local_dates,
    local_times,
    reminder_titles,
    schedules,
    timezones,
    utc_moments,
)


class TestTitle:
    @given(reminder_titles)
    def test_a_normalized_title_fits_the_column(self, title):
        normalized = normalize_reminder_title(title)

        assert 1 <= len(normalized) <= REMINDER_TITLE_MAX_LENGTH

    @given(reminder_titles)
    def test_normalization_is_idempotent(self, title):
        """The card shows the stored title, so a second pass must not move it."""
        once = normalize_reminder_title(title)

        assert normalize_reminder_title(once) == once

    @given(reminder_titles, st.text(alphabet=" \t\n", min_size=1, max_size=5))
    def test_padding_never_makes_a_different_title(self, title, padding):
        assert normalize_reminder_title(f"{padding}{title}{padding}") == normalize_reminder_title(
            title
        )

    @given(st.text(alphabet=" \t\n\r", max_size=20))
    def test_a_title_of_whitespace_alone_is_refused(self, blank):
        with pytest.raises(ValidationError):
            normalize_reminder_title(blank)

    @given(st.integers(min_value=REMINDER_TITLE_MAX_LENGTH + 1, max_value=400))
    def test_a_title_past_the_column_is_refused(self, length):
        with pytest.raises(ValidationError):
            normalize_reminder_title("x" * length)


class TestNote:
    @given(st.text(alphabet=" \t\n", max_size=10))
    def test_a_blank_note_is_no_note(self, blank):
        assert normalize_note(blank) is None

    def test_a_missing_note_stays_missing(self):
        assert normalize_note(None) is None

    def test_a_note_past_the_column_is_refused(self):
        with pytest.raises(ValidationError):
            normalize_note("n" * 1001)


class TestDate:
    @given(local_dates, st.integers(min_value=0, max_value=WIZARD_MAX_DAYS_AHEAD))
    def test_a_day_inside_the_horizon_comes_back_whole(self, today, offset):
        day = today + timedelta(days=offset)

        assert parse_user_date(format_local_date(day), today) == day

    @given(local_dates, st.integers(min_value=1, max_value=3650))
    def test_a_day_already_gone_is_refused(self, today, offset):
        past = today - timedelta(days=offset)

        with pytest.raises(ValidationError):
            parse_user_date(format_local_date(past), today)

    @given(local_dates, st.integers(min_value=1, max_value=3650))
    def test_a_day_past_the_horizon_is_refused(self, today, offset):
        far = today + timedelta(days=WIZARD_MAX_DAYS_AHEAD + offset)

        with pytest.raises(ValidationError):
            parse_user_date(format_local_date(far), today)

    @given(local_dates)
    def test_today_is_always_schedulable(self, today):
        """A reminder later the same day is the most ordinary thing to ask for."""
        assert parse_user_date(format_local_date(today), today) == today

    @pytest.mark.parametrize("raw", ["31.12.2026", "2026/12/31", "tomorrow", "", "2026-13-01"])
    def test_input_outside_the_one_format_is_refused(self, raw):
        with pytest.raises(ValidationError):
            parse_user_date(raw, datetime(2026, 6, 1, tzinfo=UTC).date())

    @given(utc_moments, timezones)
    def test_the_local_day_is_the_day_the_user_sees(self, now, tz):
        assert local_today(now, tz) == now.astimezone(tz).date()


class TestBuiltSchedules:
    @given(local_dates, local_times)
    def test_a_once_schedule_keeps_the_wall_clock_moment_it_was_given(self, day, at):
        schedule = build_once_schedule(day, at)

        assert schedule.at.date() == day
        assert schedule.at.time() == at
        assert schedule.at.tzinfo is None

    @given(st.lists(local_times, min_size=1, max_size=TIMES_MAX_LENGTH))
    def test_a_daily_schedule_is_sorted_and_free_of_duplicates(self, times):
        built = build_daily_schedule(times)

        assert built.times == sorted(set(times))
        assert built.every_n_days == 1

    @given(st.lists(local_times, min_size=1, max_size=TIMES_MAX_LENGTH))
    def test_the_order_the_user_picked_times_in_does_not_matter(self, times):
        assert build_daily_schedule(times) == build_daily_schedule(list(reversed(times)))

    def test_a_daily_schedule_needs_at_least_one_time(self):
        with pytest.raises(ValidationError):
            build_daily_schedule([])

    def test_a_daily_schedule_stops_at_the_named_limit(self):
        too_many = [time(hour=hour) for hour in range(TIMES_MAX_LENGTH + 1)]

        with pytest.raises(ValidationError):
            build_daily_schedule(too_many)

    @given(local_dates, st.integers(min_value=1, max_value=59))
    def test_a_moment_finer_than_a_minute_is_refused(self, day, second):
        with pytest.raises(ValidationError):
            build_once_schedule(day, time(7, 30, second))


class TestFirstFire:
    @given(schedules, timezones, utc_moments)
    def test_the_first_moment_is_never_behind_the_start(self, schedule, tz, starts_at):
        moment = first_fire_at(schedule, tz, starts_at)

        assume(moment is not None)
        assert moment >= starts_at
        assert moment.utcoffset() == timedelta(0)

    @given(schedules, timezones, utc_moments)
    def test_it_stays_inside_the_horizon_it_promises(self, schedule, tz, starts_at):
        moment = first_fire_at(schedule, tz, starts_at)

        assume(moment is not None)
        assert moment <= starts_at + timedelta(days=WIZARD_MAX_DAYS_AHEAD)

    @given(schedules, timezones, utc_moments)
    def test_it_is_deterministic(self, schedule, tz, starts_at):
        assert first_fire_at(schedule, tz, starts_at) == first_fire_at(schedule, tz, starts_at)

    @given(schedules, timezones, utc_moments)
    def test_nothing_fires_between_the_start_and_the_first_moment(self, schedule, tz, starts_at):
        """It is the *first* moment: the window before it has to be empty."""
        moment = first_fire_at(schedule, tz, starts_at)

        assume(moment is not None)
        assert (
            next_occurrences(schedule, tz, after=starts_at - BOUNDARY, until=moment, limit=2)[0]
            == moment
        )

    @given(schedules, timezones, utc_moments)
    def test_the_moment_at_the_boundary_is_not_lost(self, schedule, tz, starts_at):
        """`after` is exclusive; a reminder created on its own minute still fires."""
        moment = first_fire_at(schedule, tz, starts_at)

        assume(moment is not None)
        assert first_fire_at(schedule, tz, moment) == moment

    @given(local_dates, local_times, timezones)
    def test_a_once_schedule_fires_on_the_day_it_carries(self, day, at, tz):
        schedule = build_once_schedule(day, at)
        starts_at = datetime.combine(day, time(0, 0), tzinfo=UTC) - timedelta(days=2)

        moment = first_fire_at(schedule, tz, starts_at)

        assert moment == to_utc(datetime.combine(day, at), tz)

    @given(local_dates, local_times, timezones)
    def test_a_once_schedule_already_past_has_nothing_ahead(self, day, at, tz):
        """This is what the service turns into a refusal, so it must be total."""
        schedule = build_once_schedule(day, at)
        starts_at = datetime.combine(day, time(0, 0), tzinfo=UTC) + timedelta(days=3)

        assert first_fire_at(schedule, tz, starts_at) is None

    @given(local_times, timezones, utc_moments)
    def test_a_daily_schedule_always_has_something_ahead(self, at, tz, starts_at):
        """Daily repeats forever, so the wizard can never refuse one as exhausted."""
        assert first_fire_at(build_daily_schedule([at]), tz, starts_at) is not None

    @given(local_times, timezones, utc_moments)
    def test_a_daily_first_moment_is_the_wall_clock_time_the_user_picked(self, at, tz, starts_at):
        moment = first_fire_at(build_daily_schedule([at]), tz, starts_at)

        assert moment is not None
        local_day = moment.astimezone(tz).date()
        assert moment == to_utc(datetime.combine(local_day, at), tz)


class TestWeeklySchedule:
    """Acceptance: a weekly reminder fires on the days the user toggled."""

    @given(
        times=st.lists(local_times, min_size=1, max_size=TIMES_MAX_LENGTH),
        weekdays=st.lists(st.integers(1, 7), min_size=1, max_size=20),
    )
    def test_answers_survive_in_any_order_and_without_duplicates(self, times, weekdays):
        schedule = build_weekly_schedule(times, weekdays)

        assert schedule.times == sorted(set(times))
        assert schedule.weekdays == sorted(set(weekdays))

    @given(
        times=st.lists(local_times, min_size=1, max_size=TIMES_MAX_LENGTH),
        weekdays=st.lists(st.integers(1, 7), min_size=1, max_size=7, unique=True),
    )
    def test_the_order_the_buttons_were_pressed_in_does_not_matter(self, times, weekdays):
        assert build_weekly_schedule(times, weekdays) == build_weekly_schedule(
            list(reversed(times)), list(reversed(weekdays))
        )

    def test_a_week_without_a_day_is_refused(self):
        with pytest.raises(ValidationError):
            build_weekly_schedule([time(8, 0)], [])

    @given(day=st.integers().filter(lambda value: not 1 <= value <= 7))
    def test_a_day_outside_the_iso_week_is_refused(self, day):
        with pytest.raises(ValidationError):
            build_weekly_schedule([time(8, 0)], [day])


class TestMonthlySchedule:
    """Acceptance: a monthly reminder says what to do in a month that is short."""

    @given(
        times=st.lists(local_times, min_size=1, max_size=TIMES_MAX_LENGTH),
        days=st.lists(st.integers(1, 31), min_size=1, max_size=40),
        rule=st.sampled_from(["last_day", "skip"]),
    )
    def test_answers_survive_in_any_order_and_without_duplicates(self, times, days, rule):
        schedule = build_monthly_schedule(times, days, rule)

        assert schedule.days == sorted(set(days))
        assert schedule.on_missing_day == rule

    def test_a_month_without_a_day_is_refused(self):
        with pytest.raises(ValidationError):
            build_monthly_schedule([time(8, 0)], [])

    @given(day=st.integers().filter(lambda value: not 1 <= value <= MONTH_DAYS_MAX_LENGTH))
    def test_a_day_no_month_has_is_refused(self, day):
        with pytest.raises(ValidationError):
            build_monthly_schedule([time(8, 0)], [day])

    @given(rule=st.text().filter(lambda value: value not in ("last_day", "skip")))
    def test_an_unknown_missing_day_rule_is_refused(self, rule):
        """The wizard maps a button onto this value; a typo must not reach JSONB."""
        with pytest.raises(ValidationError):
            build_monthly_schedule([time(8, 0)], [15], rule)


class TestIntervalSchedule:
    """Acceptance: an interval reminder repeats inside a window of the day."""

    @given(
        every_minutes=st.integers(INTERVAL_MIN_MINUTES, INTERVAL_MAX_MINUTES),
        start=local_times,
        end=local_times,
    )
    def test_any_window_the_contract_allows_is_accepted(self, every_minutes, start, end):
        """A window crossing midnight is normal and equal ends mean all day."""
        schedule = build_interval_schedule(every_minutes, start, end)

        assert (schedule.window_start, schedule.window_end) == (start, end)

    @given(
        every_minutes=st.integers().filter(
            lambda value: not INTERVAL_MIN_MINUTES <= value <= INTERVAL_MAX_MINUTES
        )
    )
    def test_a_step_outside_the_contract_is_refused(self, every_minutes):
        with pytest.raises(ValidationError):
            build_interval_schedule(every_minutes, time(9, 0), time(21, 0))


class TestManualInterval:
    @given(minutes=st.integers(INTERVAL_MIN_MINUTES, INTERVAL_MAX_MINUTES))
    def test_a_number_inside_the_contract_round_trips(self, minutes):
        assert parse_user_interval(f"  {minutes} ") == minutes

    @given(
        minutes=st.integers().filter(
            lambda value: not INTERVAL_MIN_MINUTES <= value <= INTERVAL_MAX_MINUTES
        )
    )
    def test_a_number_outside_the_contract_is_refused(self, minutes):
        with pytest.raises(ValidationError):
            parse_user_interval(str(minutes))

    @pytest.mark.parametrize("raw", ["", "  ", "60 minutes", "1.5", "час", "9e2"])
    def test_anything_that_is_not_a_number_is_refused(self, raw):
        with pytest.raises(ValidationError):
            parse_user_interval(raw)


class TestManualWindow:
    @given(start=local_times, end=local_times)
    def test_a_typed_window_comes_back_as_the_two_times_it_names(self, start, end):
        raw = f"{format_hhmm(start)}-{format_hhmm(end)}"

        assert parse_user_window(raw) == (start, end)

    @given(start=local_times, end=local_times)
    def test_spaces_around_the_separator_are_ignored(self, start, end):
        raw = f" {format_hhmm(start)} - {format_hhmm(end)} "

        assert parse_user_window(raw) == (start, end)

    @pytest.mark.parametrize(
        "raw", ["", "09:00", "0900-2100", "09:00–21:00", "25:00-21:00", "09:00-21:60", "-"]
    )
    def test_a_window_outside_the_one_format_is_refused(self, raw):
        with pytest.raises(ValidationError):
            parse_user_window(raw)


class TestScheduleReachesTheSameFirstMoment:
    """Every kind the wizard builds is a kind the planner can materialise."""

    @given(tz=timezones, now=utc_moments)
    def test_a_weekly_schedule_fires_on_a_day_it_names(self, tz, now):
        schedule = build_weekly_schedule([time(9, 0)], [1, 4])
        moment = first_fire_at(schedule, tz, now)

        assert moment is not None
        assert moment.astimezone(tz).isoweekday() in (1, 4)

    @given(tz=timezones, now=utc_moments)
    def test_a_monthly_schedule_fires_on_a_day_it_names(self, tz, now):
        schedule = build_monthly_schedule([time(9, 0)], [1, 15], "skip")
        moment = first_fire_at(schedule, tz, now)

        assert moment is not None
        assert moment.astimezone(tz).day in (1, 15)

    @given(tz=timezones, now=utc_moments)
    def test_an_interval_schedule_fires_inside_its_window(self, tz, now):
        schedule = build_interval_schedule(60, time(9, 0), time(21, 0))
        moment = first_fire_at(schedule, tz, now)

        assert moment is not None
        assert time(9, 0) <= moment.astimezone(tz).time() <= time(21, 0)


class TestSnoozeAndRepeat:
    """Acceptance criteria of tech.md 15 (S9): the step and the automatic
    repeat are minutes the schema can hold and the reaper can act on."""

    @given(st.integers(min_value=SNOOZE_MIN_MINUTES, max_value=SNOOZE_MAX_MINUTES))
    def test_a_step_inside_the_limits_survives_the_round_trip(self, minutes):
        assert parse_user_snooze(str(minutes)) == minutes
        assert parse_user_snooze(f"  {minutes} ") == minutes

    @given(st.integers(min_value=REPEAT_MIN_MINUTES, max_value=REPEAT_MAX_MINUTES))
    def test_a_repeat_inside_the_limits_survives_the_round_trip(self, minutes):
        assert parse_user_repeat(str(minutes)) == minutes

    @given(st.integers())
    def test_a_number_outside_the_limits_is_refused(self, minutes):
        assume(not SNOOZE_MIN_MINUTES <= minutes <= SNOOZE_MAX_MINUTES)

        with pytest.raises(ValidationError):
            parse_user_snooze(str(minutes))

    @given(st.integers())
    def test_a_repeat_outside_the_limits_is_refused(self, minutes):
        assume(not REPEAT_MIN_MINUTES <= minutes <= REPEAT_MAX_MINUTES)

        with pytest.raises(ValidationError):
            parse_user_repeat(str(minutes))

    def test_zero_is_not_a_way_to_turn_the_repeat_off(self):
        """Turning it off is a button. Read as zero it would disable a reminder
        the user meant to speed up (tech.md 21.5)."""
        with pytest.raises(ValidationError):
            parse_user_repeat("0")

    @given(st.text(max_size=8))
    def test_anything_that_is_not_a_number_is_refused(self, raw):
        assume(not raw.strip().lstrip("+-").isdigit())

        with pytest.raises(ValidationError):
            parse_user_snooze(raw)
        with pytest.raises(ValidationError):
            parse_user_repeat(raw)


class TestLocalDayBounds:
    """Acceptance criteria of tech.md 15 (S9): `/today` shows the user's day,
    and a day is not always twenty-four hours long."""

    @given(day=local_dates, tz=timezones)
    def test_the_day_is_a_half_open_utc_interval(self, day, tz):
        start, end = local_day_bounds(day, tz)

        assert start.tzinfo is UTC and end.tzinfo is UTC
        assert start < end

    @given(day=local_dates, tz=timezones)
    def test_both_ends_belong_to_the_days_they_name(self, day, tz):
        start, end = local_day_bounds(day, tz)

        assert local_today(start, tz) == day
        assert local_today(end - timedelta(minutes=1), tz) == day

    @given(day=local_dates, tz=timezones)
    def test_a_day_lasts_between_23_and_25_hours(self, day, tz):
        """A DST day is short or long, never absurd. A bound outside this range
        means the resolver picked a moment in the wrong day."""
        start, end = local_day_bounds(day, tz)

        assert timedelta(hours=23) <= end - start <= timedelta(hours=25)

    @given(day=local_dates, tz=timezones)
    def test_consecutive_days_meet_without_a_gap(self, day, tz):
        """A gap would hide deliveries from `/today` on both sides of it
        (tech.md 21.8)."""
        _, end = local_day_bounds(day, tz)
        next_start, _ = local_day_bounds(day + timedelta(days=1), tz)

        assert end == next_start

    @given(day=local_dates, tz=timezones)
    def test_the_bounds_are_deterministic(self, day, tz):
        assert local_day_bounds(day, tz) == local_day_bounds(day, tz)

    @pytest.mark.parametrize("name", DST_TIMEZONE_NAMES)
    def test_a_transition_day_still_covers_its_own_midnight(self, name):
        """The days the clocks move are the days worth checking."""
        tz = ZoneInfo(name)
        for moment in transitions(tz):
            day = moment.astimezone(tz).date()
            start, end = local_day_bounds(day, tz)

            assert start <= moment < end
            assert local_today(start, tz) == day
