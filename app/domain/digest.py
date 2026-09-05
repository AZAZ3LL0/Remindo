"""When the weekly digest is due and what week it covers (tech.md 23.8).

Pure, like the other three worker brains next to it: the service owns the
transaction, the SQL and the send, while the decision about *which* digest is
owed and *when* it came due is checked by property tests rather than by a
database and a clock.
"""

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.domain.quiet_hours import QuietHours
from app.domain.recurrence import to_utc

#: A week of local days, as many ISO weekdays as there are.
DAYS_IN_WEEK = 7


@dataclass(frozen=True, slots=True)
class DigestWindow:
    """The stretch of time one digest reports on: `(start, end]`, both UTC."""

    start: datetime
    end: datetime


def last_digest_moment(now: datetime, tz: ZoneInfo, weekday: int, hour: int) -> datetime:
    """The most recent local `weekday` at `hour:00` that is not after `now`.

    ISO weekdays, Monday is 1 (tech.md 5). The local moment is resolved by the
    same `to_utc` the schedules use, so an hour that does not exist moves
    forward and an ambiguous one takes the earlier offset (tech.md 5.1).
    """
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")

    local_day = now.astimezone(tz).date()
    behind = (local_day.isoweekday() - weekday) % DAYS_IN_WEEK
    candidate = datetime.combine(local_day - timedelta(days=behind), time(hour=hour))

    moment = to_utc(candidate, tz)
    if moment > now:
        # The weekday is today but the hour has not arrived yet.
        moment = to_utc(candidate - timedelta(days=DAYS_IN_WEEK), tz)
    return moment


def digest_window(moment: datetime, tz: ZoneInfo) -> DigestWindow:
    """The seven local days ending at `moment`.

    The week is counted on the wall clock, not in 168 hours: a DST transition
    makes the week shorter or longer, and the digest keeps its local hour the
    way a daily schedule keeps its local time (tech.md 5.1). Adjacent windows
    therefore meet exactly, with no gap and no overlap.
    """
    naive = moment.astimezone(tz).replace(tzinfo=None) - timedelta(days=DAYS_IN_WEEK)
    return DigestWindow(start=to_utc(naive, tz), end=moment)


def digest_due_at(
    now: datetime,
    tz: ZoneInfo,
    *,
    weekday: int,
    hour: int,
    sent_at: datetime | None,
    quiet: QuietHours,
) -> datetime | None:
    """The weekly moment still owed, or `None` when nothing is.

    The moment comes back unshifted even when quiet hours delay the send: it
    is both the idempotency key of the cycle and the end of the window
    (tech.md 23.5, 23.6). Shifting what gets stored would let a silence that
    ends after midnight pass two digests off as one week.
    """
    moment = last_digest_moment(now, tz, weekday, hour)
    if sent_at is not None and sent_at >= moment:
        return None
    if quiet.shift(moment) > now:
        return None
    return moment
