"""Pure planner arithmetic: which window one cycle materialises (tech.md 7.1).

The service owns transactions and SQL. Every decision about *what* to
materialise lives here, so the three boundaries that actually lose data when
they are wrong — the horizon, `ends_at` and `max_occurrences` — are covered by
property tests instead of by a database.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Final
from zoneinfo import ZoneInfo

from app.domain.recurrence import to_utc
from app.domain.reminders import BOUNDARY
from app.domain.schedules import OnceSchedule, Schedule

#: Ceiling on occurrences one cycle writes for one reminder. A dense interval
#: schedule outruns a 48h horizon, and an unbounded insert would hold the
#: transaction while the rest of the batch waits.
MAX_OCCURRENCES_PER_CYCLE: Final = 500


@dataclass(frozen=True, slots=True)
class PlanBounds:
    """Everything the planner is allowed to know about one reminder."""

    starts_at: datetime
    planned_until: datetime | None = None
    ends_at: datetime | None = None
    max_occurrences: int | None = None
    #: Final moment the schedule can ever produce; `None` when it recurs forever.
    last_moment: datetime | None = None


@dataclass(frozen=True, slots=True)
class PlanWindow:
    """Range handed to `next_occurrences`: `after` exclusive, `until` inclusive."""

    after: datetime
    until: datetime
    limit: int

    @property
    def is_empty(self) -> bool:
        return self.limit <= 0 or self.until <= self.after


@dataclass(frozen=True, slots=True)
class PlanOutcome:
    planned_until: datetime
    exhausted: bool


def last_moment_of(schedule: Schedule, tz: ZoneInfo) -> datetime | None:
    """Final moment `schedule` can ever produce, or `None` when it recurs forever.

    Only a `once` schedule ends on its own. Without this the planner would keep
    reselecting a one-shot reminder whose minute has passed, every cycle, for as
    long as the row exists.
    """
    if isinstance(schedule, OnceSchedule):
        return to_utc(schedule.at, tz)
    return None


def plan_window(
    bounds: PlanBounds,
    *,
    horizon_end: datetime,
    fired_count: int,
    batch_limit: int = MAX_OCCURRENCES_PER_CYCLE,
) -> PlanWindow:
    """Range this cycle may materialise, clamped by every boundary at once."""
    # `after` is exclusive, so a moment landing exactly on starts_at survives.
    # The wizard nudges the same boundary (tech.md 18.6), which is why both read
    # it from one constant instead of writing the microsecond down twice.
    after = bounds.starts_at - BOUNDARY
    if bounds.planned_until is not None and bounds.planned_until > after:
        after = bounds.planned_until

    until = horizon_end if bounds.ends_at is None else min(horizon_end, bounds.ends_at)

    limit = batch_limit
    if bounds.max_occurrences is not None:
        limit = min(limit, max(bounds.max_occurrences - fired_count, 0))

    return PlanWindow(after=after, until=until, limit=limit)


def settle_plan(
    bounds: PlanBounds,
    window: PlanWindow,
    moments: Sequence[datetime],
    fired_count: int,
) -> PlanOutcome:
    """Where the horizon now ends, and whether the reminder has run out.

    `fired_count` is the number of occurrences that exist after the write.
    """
    if moments and len(moments) >= window.limit:
        # The limit truncated the window: resume from the last moment written,
        # never from `until`, or everything past it is dropped in silence.
        planned_until = moments[-1]
    else:
        planned_until = max(window.after, window.until)

    return PlanOutcome(
        planned_until=planned_until,
        exhausted=_is_exhausted(bounds, planned_until, fired_count),
    )


def _is_exhausted(bounds: PlanBounds, planned_until: datetime, fired_count: int) -> bool:
    if bounds.max_occurrences is not None and fired_count >= bounds.max_occurrences:
        return True
    if bounds.ends_at is not None and planned_until >= bounds.ends_at:
        return True
    return bounds.last_moment is not None and planned_until >= bounds.last_moment
