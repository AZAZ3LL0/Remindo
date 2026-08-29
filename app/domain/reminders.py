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
    TIMES_MAX_LENGTH,
    DailySchedule,
    OnceSchedule,
    Schedule,
    parse_hhmm,
    parse_local_date,
)

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
    unique = {_wall_time(value) for value in times}
    if not 1 <= len(unique) <= TIMES_MAX_LENGTH:
        raise ValidationError(f"a daily schedule needs 1..{TIMES_MAX_LENGTH} times")
    return DailySchedule(times=sorted(unique))


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


def _wall_time(value: time) -> time:
    """One wall-clock format for the whole product (tech.md 16.2)."""
    try:
        return parse_hhmm(value)
    except ValueError as exc:
        raise ValidationError(f"unclear wall-clock time: {value!r}") from exc
