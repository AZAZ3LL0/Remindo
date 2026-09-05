"""Streaks and completion rates. Pure, order-independent, clock-free."""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Final
from zoneinfo import ZoneInfo

from app.domain.contracts import ActionKind

#: Reactions that count as an outcome. A snooze postpones, it does not resolve.
OUTCOME_KINDS = frozenset({ActionKind.DONE, ActionKind.SKIP, ActionKind.AUTO_EXPIRE})

#: How far back the journal is read, and the longest window reported over
#: (tech.md 23.2). One number, because a monthly rate computed from a week of
#: history would be a monthly rate in name only.
STATS_HISTORY_DAYS: Final = 30

#: The windows the summary reports, in days. Rolling half-open intervals
#: `(now - N days, now]`, not calendar weeks: a calendar window jumps on a DST
#: transition and on a move, and a completion rate must not change because
#: somebody changed timezone (tech.md 23.1).
STATS_WINDOW_DAYS: Final[tuple[int, int]] = (7, 30)


@dataclass(frozen=True, slots=True)
class ActionRecord:
    happened_at: datetime
    kind: ActionKind
    #: The category of the reminder this reaction answered, read through the
    #: reminder at query time rather than frozen into the journal: editing a
    #: category moves a reminder's whole history with it (tech.md 23.1).
    category_id: int = 0


@dataclass(frozen=True, slots=True)
class PeriodStats:
    completed: int
    total: int

    @property
    def rate(self) -> float:
        return self.completed / self.total if self.total else 0.0


@dataclass(frozen=True, slots=True)
class CategoryStats:
    category_id: int
    current_streak: int
    longest_streak: int
    last_7_days: PeriodStats
    last_30_days: PeriodStats


@dataclass(frozen=True, slots=True)
class StatsSummary:
    current_streak: int
    longest_streak: int
    last_7_days: PeriodStats
    last_30_days: PeriodStats
    by_category: tuple[CategoryStats, ...] = ()


def build_summary(
    records: Iterable[ActionRecord],
    tz: ZoneInfo,
    now: datetime,
) -> StatsSummary:
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")

    outcomes = [record for record in records if record.kind in OUTCOME_KINDS]
    streaks, week, month = _measure(outcomes, tz, now)

    return StatsSummary(
        current_streak=streaks[0],
        longest_streak=streaks[1],
        last_7_days=week,
        last_30_days=month,
        by_category=_breakdown(outcomes, tz, now),
    )


def _breakdown(
    outcomes: Sequence[ActionRecord], tz: ZoneInfo, now: datetime
) -> tuple[CategoryStats, ...]:
    """One entry per category with at least one outcome, ordered by id.

    Sorted rather than left in journal order so the same history always
    renders the same screen; the row order of a query is not a guarantee.
    """
    result = []
    for category_id in sorted({record.category_id for record in outcomes}):
        slice_ = [record for record in outcomes if record.category_id == category_id]
        streaks, week, month = _measure(slice_, tz, now)
        result.append(
            CategoryStats(
                category_id=category_id,
                current_streak=streaks[0],
                longest_streak=streaks[1],
                last_7_days=week,
                last_30_days=month,
            )
        )
    return tuple(result)


def _measure(
    outcomes: Sequence[ActionRecord], tz: ZoneInfo, now: datetime
) -> tuple[tuple[int, int], PeriodStats, PeriodStats]:
    """Streaks and both windows over one set of outcomes."""
    done_days = {
        record.happened_at.astimezone(tz).date()
        for record in outcomes
        if record.kind is ActionKind.DONE
    }
    today = now.astimezone(tz).date()
    week, month = (_period(outcomes, now, days=days) for days in STATS_WINDOW_DAYS)
    return (current_streak(done_days, today), longest_streak(done_days)), week, month


def current_streak(done_days: set[date], today: date) -> int:
    """Consecutive days with at least one completion, ending today or yesterday.

    An empty today does not break the streak until the day is over.
    """
    cursor = today if today in done_days else today - timedelta(days=1)
    streak = 0
    while cursor in done_days:
        streak += 1
        cursor -= timedelta(days=1)
    return streak


def longest_streak(done_days: set[date]) -> int:
    best = 0
    for day in done_days:
        if day - timedelta(days=1) in done_days:
            continue  # not the start of a run
        length = 0
        cursor = day
        while cursor in done_days:
            length += 1
            cursor += timedelta(days=1)
        best = max(best, length)
    return best


def _period(records: Sequence[ActionRecord], now: datetime, days: int) -> PeriodStats:
    since = now - timedelta(days=days)
    window = [record for record in records if since < record.happened_at <= now]
    completed = sum(1 for record in window if record.kind is ActionKind.DONE)
    return PeriodStats(completed=completed, total=len(window))
