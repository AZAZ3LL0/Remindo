"""Quiet hours shift delivery to the end of the silent interval, never drop it."""

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.domain.recurrence import to_utc


def is_quiet(moment_local: time, quiet_start: time, quiet_end: time) -> bool:
    """Membership in the local silent interval [quiet_start, quiet_end)."""
    if quiet_start == quiet_end:
        return False
    if quiet_start < quiet_end:
        return quiet_start <= moment_local < quiet_end
    # The interval crosses midnight.
    return moment_local >= quiet_start or moment_local < quiet_end


def apply_quiet_hours(
    fire_at: datetime,
    tz: ZoneInfo,
    quiet_start: time | None,
    quiet_end: time | None,
) -> datetime:
    """Return the delivery moment for a planned occurrence.

    Outside quiet hours the moment is untouched. Inside, it moves to the end of
    the interval. The result is never earlier than `fire_at`.
    """
    if fire_at.tzinfo is None:
        raise ValueError("fire_at must be timezone-aware")
    if quiet_start is None or quiet_end is None:
        return fire_at

    local = fire_at.astimezone(tz)
    if not is_quiet(local.time(), quiet_start, quiet_end):
        return fire_at

    crosses_midnight = quiet_start > quiet_end
    end_date = local.date()
    if crosses_midnight and local.time() >= quiet_start:
        end_date += timedelta(days=1)

    return _resolve_end(fire_at, tz, end_date, quiet_end)


def _resolve_end(fire_at: datetime, tz: ZoneInfo, end_date: date, quiet_end: time) -> datetime:
    """Map the local end of the interval onto an instant after `fire_at`.

    A fall-back transition repeats the local hour, so the earlier offset can
    land before `fire_at`. The later offset resolves that, and a full day is
    the last resort.
    """
    naive = datetime.combine(end_date, quiet_end)
    candidate = to_utc(naive, tz)
    if candidate > fire_at:
        return candidate

    later = naive.replace(tzinfo=tz, fold=1)
    if later > fire_at:
        return later.astimezone(fire_at.tzinfo)

    return to_utc(naive + timedelta(days=1), tz)
