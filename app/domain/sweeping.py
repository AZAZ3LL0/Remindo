"""Pure reaper decisions: what one sweep does to a delivery (tech.md 7.3).

The service owns transactions, SQL and the message edit. Every decision about
*whether* an occurrence is overdue and *when* an unanswered reminder comes back
lives here, so the two rules that lose or duplicate a reminder when they are
wrong are covered by property tests instead of by a database and a clock.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

from app.domain.contracts import TERMINAL_OCCURRENCE_STATUSES, OccurrenceStatus
from app.domain.quiet_hours import QuietHours


@dataclass(frozen=True, slots=True)
class RepeatPlan:
    """When an unanswered delivery goes back into the queue."""

    next_attempt_at: datetime


def is_overdue(status: OccurrenceStatus, expires_at: datetime, now: datetime) -> bool:
    """The occurrence outlived its TTL and accepts no more reactions.

    A terminal occurrence is left alone: somebody answered it, and expiring it
    afterwards would overwrite that answer with silence.
    """
    if status in TERMINAL_OCCURRENCE_STATUSES:
        return False
    return expires_at < now


def decide_repeat(
    *,
    sent_at: datetime | None,
    repeat_after_minutes: int | None,
    repeats_sent: int,
    max_repeats: int,
    expires_at: datetime,
    quiet: QuietHours,
    now: datetime,
) -> RepeatPlan | None:
    """Moment an unanswered reminder is sent again, or `None` for no repeat.

    The repeat is a delivery like any other, so it obeys quiet hours: a
    reminder that went out at 22:55 does not come back at 23:25 into silence
    the user configured.
    """
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    if repeat_after_minutes is None or sent_at is None:
        return None
    if repeats_sent >= max_repeats:
        return None
    if sent_at + timedelta(minutes=repeat_after_minutes) > now:
        return None

    moment = quiet.shift(now)
    if moment >= expires_at:
        # Silence outlasts the occurrence. Sending anyway would put buttons on
        # screen that are dead on arrival, and the next sweep expires the
        # occurrence regardless, so the repeat is dropped instead of deferred.
        return None
    return RepeatPlan(next_attempt_at=moment)
