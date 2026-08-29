"""Validation of personal settings: language, timezone and quiet hours.

Pure by contract (tech.md 3): no clock, no IO, no imports outside stdlib. Every
rule here is the reason a service is allowed to write the row, so the service
never decides validity on its own.
"""

from datetime import time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.domain.contracts import Language
from app.domain.errors import ValidationError
from app.domain.schedules import parse_hhmm

#: Longest IANA name in the database is well under this; the cap only keeps
#: absurd input away from the column.
MAX_TIMEZONE_LENGTH = 64


def normalize_language(raw: str) -> Language:
    """Map user input onto a supported language."""
    try:
        return Language(raw.strip().lower())
    except ValueError as exc:
        raise ValidationError(f"unsupported language: {raw!r}") from exc


def normalize_timezone(raw: str) -> str:
    """Accept an IANA name `zoneinfo` can resolve, and return it unchanged.

    Names are case-sensitive: `europe/moscow` is not a zone, and silently
    fixing the case would hide a typo the user needs to see.
    """
    name = raw.strip()
    if not name or len(name) > MAX_TIMEZONE_LENGTH:
        raise ValidationError(f"unknown timezone: {raw!r}")
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValidationError(f"unknown timezone: {raw!r}") from exc
    return name


def parse_wall_time(raw: str) -> time:
    """Parse `HH:MM` typed by the user into a naive, minute-precise time."""
    try:
        return parse_hhmm(raw.strip())
    except ValueError as exc:
        raise ValidationError(f"unclear wall-clock time: {raw!r}") from exc


def normalize_quiet_hours(
    quiet_start: time | None, quiet_end: time | None
) -> tuple[time, time] | None:
    """Validate a quiet interval, or `None` when quiet hours are switched off.

    Crossing midnight is normal, so `quiet_start > quiet_end` is allowed. Equal
    bounds are not: `apply_quiet_hours` treats such an interval as empty, so the
    setting would look saved and never do anything.
    """
    if quiet_start is None and quiet_end is None:
        return None
    if quiet_start is None or quiet_end is None:
        raise ValidationError("quiet hours must be set or cleared together")
    for bound in (quiet_start, quiet_end):
        if bound.tzinfo is not None or bound.second or bound.microsecond:
            raise ValidationError("quiet hours must be naive and minute-precise")
    if quiet_start == quiet_end:
        raise ValidationError("quiet hours start and end must differ")
    return quiet_start, quiet_end
