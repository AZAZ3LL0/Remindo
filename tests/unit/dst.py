"""Where the clocks actually move, found rather than written down.

The transition dates of four zones over several years are data nobody should
retype, and a hardcoded table quietly rots when tzdata ships a new release.
These helpers read the transitions out of `zoneinfo` itself, so the invariants
in `test_recurrence.py` describe the rule and let the library supply the dates.
"""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

#: Years scanned for transitions. Wide enough to cover both hemispheres several
#: times over without making the scan noticeable.
SCAN_YEARS = (2026, 2027)

_HOUR = timedelta(hours=1)
_SECOND = timedelta(seconds=1)


def offset_at(moment: datetime, tz: ZoneInfo) -> timedelta:
    offset = moment.astimezone(tz).utcoffset()
    assert offset is not None
    return offset


def local_naive(moment: datetime, tz: ZoneInfo) -> datetime:
    return moment.astimezone(tz).replace(tzinfo=None)


def transitions(tz: ZoneInfo, years: tuple[int, ...] = SCAN_YEARS) -> list[datetime]:
    """UTC instants inside `years` where the offset of `tz` changes.

    Found by scanning hour by hour and then narrowing to the second: transitions
    land on whole minutes, so an hourly sweep cannot miss one.
    """
    found: list[datetime] = []
    moment = datetime(years[0], 1, 1, tzinfo=UTC)
    end = datetime(years[-1] + 1, 1, 1, tzinfo=UTC)
    previous = offset_at(moment, tz)

    while moment < end:
        moment += _HOUR
        current = offset_at(moment, tz)
        if current != previous:
            found.append(_narrow(moment - _HOUR, moment, tz))
            previous = current
    return found


def _narrow(low: datetime, high: datetime, tz: ZoneInfo) -> datetime:
    """Earliest instant in `(low, high]` carrying the offset that `high` has."""
    target = offset_at(high, tz)
    while high - low > _SECOND:
        middle = low + (high - low) / 2
        if offset_at(middle, tz) == target:
            high = middle
        else:
            low = middle
    return high.replace(microsecond=0)


def nonexistent_local_time(transition: datetime, tz: ZoneInfo) -> datetime | None:
    """A naive local moment the clock skipped over, or `None` at a fall back."""
    gap = offset_at(transition, tz) - offset_at(transition - _SECOND, tz)
    if gap <= timedelta(0):
        return None
    return local_naive(transition, tz) - gap / 2


def ambiguous_local_time(transition: datetime, tz: ZoneInfo) -> datetime | None:
    """A naive local moment the clock passed twice, or `None` at a spring forward."""
    gap = offset_at(transition - _SECOND, tz) - offset_at(transition, tz)
    if gap <= timedelta(0):
        return None
    return local_naive(transition, tz) + gap / 2


def is_nonexistent(naive: datetime, tz: ZoneInfo) -> bool:
    """True when the local clock never showed `naive` in `tz`."""
    return local_naive(naive.replace(tzinfo=tz).astimezone(UTC), tz) != naive
