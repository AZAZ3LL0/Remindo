"""Validation of the draft the creation wizard collects (tech.md 18.6).

Pure by contract (tech.md 3): no clock, no IO, no imports outside stdlib and
`app/domain`. Every rule here is the reason the service is allowed to write a
row, so the service never decides validity on its own.
"""

from collections.abc import Sequence
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.domain.contracts import (
    REMINDER_NOTE_MAX_LENGTH,
    REMINDER_TITLE_MAX_LENGTH,
    WIZARD_MAX_DAYS_AHEAD,
)
from app.domain.errors import ValidationError
from app.domain.recurrence import next_occurrences
from app.domain.schedules import (
    INTERVAL_MAX_MINUTES,
    INTERVAL_MIN_MINUTES,
    MONTH_DAYS_MAX_LENGTH,
    TIMES_MAX_LENGTH,
    WEEKDAYS_MAX_LENGTH,
    DailySchedule,
    IntervalSchedule,
    MonthlySchedule,
    OnceSchedule,
    Schedule,
    WeeklySchedule,
    parse_hhmm,
    parse_local_date,
)

#: Separator between the two ends of a hand-typed day window.
WINDOW_SEPARATOR = "-"

#: `next_occurrences` treats `after` as exclusive. The planner nudges the
#: boundary by this much (tech.md 7.1) and so does the wizard: otherwise the
#: two would disagree about the first moment of a brand new reminder.
BOUNDARY = timedelta(microseconds=1)


def normalize_reminder_title(raw: str) -> str:
    """Trim the edges and collapse inner whitespace, then check the length.

    Same rule as a category title (tech.md 17.6): what the user sees in the
    card is what the wizard stored, not what the keyboard happened to send.
    """
    title = " ".join(raw.split())
    if not 1 <= len(title) <= REMINDER_TITLE_MAX_LENGTH:
        raise ValidationError(f"reminder title must be 1..{REMINDER_TITLE_MAX_LENGTH} characters")
    return title


def normalize_note(raw: str | None) -> str | None:
    """An optional note, or `None`. Whitespace alone is not a note."""
    if raw is None:
        return None
    note = raw.strip()
    if not note:
        return None
    if len(note) > REMINDER_NOTE_MAX_LENGTH:
        raise ValidationError(f"reminder note must be at most {REMINDER_NOTE_MAX_LENGTH} chars")
    return note


def local_today(now: datetime, tz: ZoneInfo) -> date:
    """The user's current calendar day. `now` always arrives from a Clock."""
    return now.astimezone(tz).date()


def parse_user_date(raw: str, today: date, max_days_ahead: int = WIZARD_MAX_DAYS_AHEAD) -> date:
    """A `YYYY-MM-DD` day inside `[today, today + max_days_ahead]`.

    Yesterday and a date past the horizon are refused the same way: both are
    days the wizard cannot schedule anything on, and telling them apart would
    only add a message nobody acts on differently.
    """
    try:
        day = parse_local_date(raw.strip())
    except ValueError as exc:
        raise ValidationError(f"unclear date: {raw!r}") from exc
    if not today <= day <= today + timedelta(days=max_days_ahead):
        raise ValidationError(f"date outside the wizard horizon: {day.isoformat()}")
    return day


def build_once_schedule(day: date, at: time) -> OnceSchedule:
    """A single wall-clock moment on `day` (tech.md 5)."""
    return OnceSchedule(at=datetime.combine(day, _wall_time(at)))


def build_daily_schedule(times: Sequence[time]) -> DailySchedule:
    """Every day at each of `times`. Duplicates collapse, order does not matter."""
    return DailySchedule(times=_times(times))


def build_weekly_schedule(times: Sequence[time], weekdays: Sequence[int]) -> WeeklySchedule:
    """Every chosen weekday at each of `times`, ISO numbering (tech.md 5)."""
    return WeeklySchedule(
        times=_times(times),
        weekdays=_day_numbers(weekdays, 1, WEEKDAYS_MAX_LENGTH, "weekday"),
    )


def build_monthly_schedule(
    times: Sequence[time], days: Sequence[int], on_missing_day: str = "last_day"
) -> MonthlySchedule:
    """Every chosen day of the month at each of `times`.

    `on_missing_day` decides February: `last_day` moves the 31st onto the last
    day the month has, `skip` drops the month (tech.md 5).
    """
    if on_missing_day not in ("last_day", "skip"):
        raise ValidationError(f"unknown missing-day rule: {on_missing_day!r}")
    return MonthlySchedule(
        times=_times(times),
        days=_day_numbers(days, 1, MONTH_DAYS_MAX_LENGTH, "day of month"),
        on_missing_day=on_missing_day,
    )


def build_interval_schedule(
    every_minutes: int, window_start: time, window_end: time
) -> IntervalSchedule:
    """A step repeated inside one activity window.

    The window is mandatory: tech.md 5 defines no interval schedule without
    one, and equal ends mean the whole day rather than nothing.
    """
    if not INTERVAL_MIN_MINUTES <= every_minutes <= INTERVAL_MAX_MINUTES:
        raise ValidationError(
            f"interval must be {INTERVAL_MIN_MINUTES}..{INTERVAL_MAX_MINUTES} minutes"
        )
    return IntervalSchedule(
        every_minutes=every_minutes,
        window_start=_wall_time(window_start),
        window_end=_wall_time(window_end),
    )


def parse_user_interval(raw: str) -> int:
    """A hand-typed step in minutes, inside the limits of tech.md 5."""
    try:
        minutes = int(raw.strip())
    except ValueError as exc:
        raise ValidationError(f"unclear interval: {raw!r}") from exc
    if not INTERVAL_MIN_MINUTES <= minutes <= INTERVAL_MAX_MINUTES:
        raise ValidationError(
            f"interval must be {INTERVAL_MIN_MINUTES}..{INTERVAL_MAX_MINUTES} minutes"
        )
    return minutes


def parse_user_window(raw: str) -> tuple[time, time]:
    """A hand-typed `HH:MM-HH:MM` window.

    Both halves go through the one wall-clock parser (tech.md 16.2). A window
    crossing midnight is normal, and equal ends mean twenty-four hours.
    """
    start, separator, end = raw.strip().partition(WINDOW_SEPARATOR)
    if not separator:
        raise ValidationError(f"unclear window: {raw!r}")
    try:
        return parse_hhmm(start.strip()), parse_hhmm(end.strip())
    except ValueError as exc:
        raise ValidationError(f"unclear window: {raw!r}") from exc


def first_fire_at(
    schedule: Schedule,
    tz: ZoneInfo,
    starts_at: datetime,
    max_days_ahead: int = WIZARD_MAX_DAYS_AHEAD,
) -> datetime | None:
    """First moment the planner would materialise, or `None` if there is none.

    The wizard shows this on the card and the service refuses a schedule that
    has none: a `once` reminder on a minute already gone is never materialised,
    and a row created in silence would look like it works.
    """
    moments = next_occurrences(
        schedule,
        tz,
        after=starts_at - BOUNDARY,
        until=starts_at + timedelta(days=max_days_ahead),
        limit=1,
    )
    return moments[0] if moments else None


def _times(values: Sequence[time]) -> list[time]:
    """The shared rule for a list of wall-clock times: unique, sorted, bounded."""
    unique = {_wall_time(value) for value in values}
    if not 1 <= len(unique) <= TIMES_MAX_LENGTH:
        raise ValidationError(f"a schedule needs 1..{TIMES_MAX_LENGTH} times")
    return sorted(unique)


def _day_numbers(values: Sequence[int], low: int, high: int, what: str) -> list[int]:
    """Day numbers of a week or a month: unique, sorted, inside the range."""
    unique = set(values)
    if not unique:
        raise ValidationError(f"a schedule needs at least one {what}")
    if not all(low <= value <= high for value in unique):
        raise ValidationError(f"{what} must be {low}..{high}")
    return sorted(unique)


def _wall_time(value: time) -> time:
    """One wall-clock format for the whole product (tech.md 16.2)."""
    try:
        return parse_hhmm(value)
    except ValueError as exc:
        raise ValidationError(f"unclear wall-clock time: {value!r}") from exc
