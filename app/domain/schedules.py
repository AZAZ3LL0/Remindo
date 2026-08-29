"""Schedule contract stored in `reminders.schedule` (JSONB).

Discriminated union on `kind`. Every time in this module is local wall-clock
time in `reminders.timezone`; nothing here is timezone-aware and nothing here
reads a clock.
"""

import re
from datetime import date, datetime, time
from typing import Annotated, Any, Final, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PlainSerializer,
    TypeAdapter,
    field_validator,
)

from app.domain.contracts import ScheduleKind

#: How many wall-clock times one schedule may carry (tech.md 5). Named so the
#: wizard can refuse a thirteenth time with the same number the model enforces.
TIMES_MAX_LENGTH: Final = 12

_HHMM = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_LOCAL_DT = re.compile(r"^\d{4}-\d{2}-\d{2}T([01]\d|2[0-3]):([0-5]\d)$")


def parse_hhmm(value: Any) -> time:
    """Wall-clock `HH:MM` in 24-hour format. Raises ValueError on anything else.

    Public because every wall-clock time in the product speaks this one format:
    schedules, quiet hours and manual input all parse through here.
    """
    if isinstance(value, time):
        if value.tzinfo is not None or value.second or value.microsecond:
            raise ValueError("time must be naive and minute-precise")
        return value
    if not isinstance(value, str) or not _HHMM.match(value):
        raise ValueError("time must match HH:MM in 24-hour format")
    hour, minute = value.split(":")
    return time(int(hour), int(minute))


def format_hhmm(value: time) -> str:
    """Inverse of `parse_hhmm`."""
    return f"{value.hour:02d}:{value.minute:02d}"


def parse_local_date(value: Any) -> date:
    """Calendar date as `YYYY-MM-DD`. Raises ValueError on anything else.

    Public for the same reason `parse_hhmm` is: the product speaks one date
    format, in the `once` payload and in manual input alike (tech.md 18.3).
    """
    if isinstance(value, datetime):
        raise ValueError("date must not carry a time")
    if isinstance(value, date):
        return value
    if not isinstance(value, str) or not _ISO_DATE.match(value):
        raise ValueError("date must match YYYY-MM-DD")
    return date.fromisoformat(value)


def format_local_date(value: date) -> str:
    """Inverse of `parse_local_date`."""
    return value.isoformat()


def _parse_local_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is not None or value.second or value.microsecond:
            raise ValueError("local datetime must be naive and minute-precise")
        return value
    if not isinstance(value, str) or not _LOCAL_DT.match(value):
        raise ValueError("local datetime must match YYYY-MM-DDTHH:MM")
    return datetime.strptime(value, "%Y-%m-%dT%H:%M")  # noqa: DTZ007 - wall-clock by contract


def _format_local_datetime(value: datetime) -> str:
    return value.strftime("%Y-%m-%dT%H:%M")


LocalTime = Annotated[
    time,
    Field(json_schema_extra={"format": "HH:MM"}),
    PlainSerializer(format_hhmm, return_type=str),
]
LocalDateTime = Annotated[
    datetime,
    PlainSerializer(_format_local_datetime, return_type=str),
]


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class _WithTimes(_Base):
    times: Annotated[list[LocalTime], Field(min_length=1, max_length=TIMES_MAX_LENGTH)]

    @field_validator("times", mode="before")
    @classmethod
    def _coerce_times(cls, value: Any) -> Any:
        if isinstance(value, list):
            return [parse_hhmm(item) for item in value]
        return value

    @field_validator("times", mode="after")
    @classmethod
    def _normalize_times(cls, value: list[time]) -> list[time]:
        return sorted(set(value))


class OnceSchedule(_Base):
    kind: Literal[ScheduleKind.ONCE] = ScheduleKind.ONCE
    at: LocalDateTime

    @field_validator("at", mode="before")
    @classmethod
    def _coerce_at(cls, value: Any) -> datetime:
        return _parse_local_datetime(value)


class IntervalSchedule(_Base):
    kind: Literal[ScheduleKind.INTERVAL] = ScheduleKind.INTERVAL
    every_minutes: Annotated[int, Field(ge=5, le=1440)]
    window_start: LocalTime
    window_end: LocalTime

    @field_validator("window_start", "window_end", mode="before")
    @classmethod
    def _coerce_window(cls, value: Any) -> time:
        return parse_hhmm(value)


class DailySchedule(_WithTimes):
    kind: Literal[ScheduleKind.DAILY] = ScheduleKind.DAILY
    every_n_days: Annotated[int, Field(ge=1, le=366)] = 1


class WeeklySchedule(_WithTimes):
    kind: Literal[ScheduleKind.WEEKLY] = ScheduleKind.WEEKLY
    weekdays: Annotated[list[Annotated[int, Field(ge=1, le=7)]], Field(min_length=1, max_length=7)]

    @field_validator("weekdays", mode="after")
    @classmethod
    def _normalize_weekdays(cls, value: list[int]) -> list[int]:
        return sorted(set(value))


class MonthlySchedule(_WithTimes):
    kind: Literal[ScheduleKind.MONTHLY] = ScheduleKind.MONTHLY
    days: Annotated[list[Annotated[int, Field(ge=1, le=31)]], Field(min_length=1, max_length=31)]
    on_missing_day: Literal["last_day", "skip"] = "last_day"

    @field_validator("days", mode="after")
    @classmethod
    def _normalize_days(cls, value: list[int]) -> list[int]:
        return sorted(set(value))


Schedule = Annotated[
    OnceSchedule | IntervalSchedule | DailySchedule | WeeklySchedule | MonthlySchedule,
    Field(discriminator="kind"),
]

SCHEDULE_ADAPTER: TypeAdapter[Schedule] = TypeAdapter(Schedule)


def parse_schedule(payload: Any) -> Schedule:
    """Validate a JSONB payload against the contract."""
    return SCHEDULE_ADAPTER.validate_python(payload)


def dump_schedule(schedule: Schedule) -> dict[str, Any]:
    """Render a schedule back into its JSONB representation."""
    payload: dict[str, Any] = SCHEDULE_ADAPTER.dump_python(schedule, mode="json")
    return payload
