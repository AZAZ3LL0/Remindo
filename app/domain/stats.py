"""Streaks and completion rates. Pure, order-independent, clock-free."""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.domain.contracts import ActionKind

#: Reactions that count as an outcome. A snooze postpones, it does not resolve.
OUTCOME_KINDS = frozenset({ActionKind.DONE, ActionKind.SKIP, ActionKind.AUTO_EXPIRE})


@dataclass(frozen=True, slots=True)
class ActionRecord:
    happened_at: datetime
    kind: ActionKind


@dataclass(frozen=True, slots=True)
class PeriodStats:
    completed: int
    total: int

    @property
    def rate(self) -> float:
        return self.completed / self.total if self.total else 0.0


@dataclass(frozen=True, slots=True)
class StatsSummary:
    current_streak: int
    longest_streak: int
    last_7_days: PeriodStats
    last_30_days: PeriodStats


def build_summary(
    records: Iterable[ActionRecord],
    tz: ZoneInfo,
    now: datetime,
) -> StatsSummary:
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")

    outcomes = [record for record in records if record.kind in OUTCOME_KINDS]
    done_days = {
        record.happened_at.astimezone(tz).date()
        for record in outcomes
        if record.kind is ActionKind.DONE
    }
    today = now.astimezone(tz).date()

    return StatsSummary(
        current_streak=current_streak(done_days, today),
        longest_streak=longest_streak(done_days),
        last_7_days=_period(outcomes, now, days=7),
        last_30_days=_period(outcomes, now, days=30),
    )


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


def _period(records: list[ActionRecord], now: datetime, days: int) -> PeriodStats:
    since = now - timedelta(days=days)
    window = [record for record in records if since < record.happened_at <= now]
    completed = sum(1 for record in window if record.kind is ActionKind.DONE)
    return PeriodStats(completed=completed, total=len(window))
