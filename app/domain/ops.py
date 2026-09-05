"""Pure ops decisions: what the worker knows about itself (tech.md 24).

The service owns transactions, SQL and the network call. Every decision about
*how far behind* the queue is, *whether* a cycle stopped turning and *when* an
alert is worth sending lives here, so the numbers an operator acts on are
checked by property tests instead of by a database and a clock.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Final

from app.domain.contracts import HealthStatus, JobId

#: A cycle is stale once it has missed this many of its own periods. The floor
#: exists for the dispatcher: its period is ten seconds, and three of those is
#: less than one planner tick, so a normal pause in one cycle would read as a
#: failure in its neighbour.
HEALTH_STALE_FACTOR: Final = 3
HEALTH_STALE_FLOOR_SECONDS: Final = 60


class AlertState(StrEnum):
    """What the monitor believed about delivery on its previous tick."""

    CLEAR = "clear"
    FIRING = "firing"


class AlertKind(StrEnum):
    """The edge worth one message. Never emitted twice for the same edge."""

    RAISED = "raised"
    CLEARED = "cleared"


@dataclass(frozen=True, slots=True)
class QueueSnapshot:
    """One reading of the delivery queue, taken at a single moment.

    `delivered` and `failed` count the window of tech.md 24.2; deliveries still
    waiting fall into neither, because they say nothing about transport yet.
    """

    due_deliveries: int = 0
    oldest_due_at: datetime | None = None
    delivered: int = 0
    failed: int = 0


@dataclass(frozen=True, slots=True)
class OpsReport:
    """The three numbers of tech.md 24.2, plus when they were read."""

    taken_at: datetime
    queue_size: int
    lag: timedelta
    error_ratio: float


@dataclass(frozen=True, slots=True)
class CycleBeat:
    """Last time one worker cycle attempted its work.

    The mark is stamped on every attempt, failed ones included: a database that
    blinks knocks over the cycles while the loop keeps turning, and a restart
    at that moment cures nothing.
    """

    job: JobId
    interval_seconds: float
    last_tick_at: datetime
    failures: int = 0


@dataclass(frozen=True, slots=True)
class AlertDecision:
    """What the monitor believes now, and the one message it owes."""

    state: AlertState
    notify: AlertKind | None = None


def queue_lag(snapshot: QueueSnapshot, now: datetime) -> timedelta:
    """How long the oldest due delivery has been waiting. Never negative.

    A queue whose next attempt is in the future is on time, not ahead of
    schedule, so it lags by zero.
    """
    _require_aware(now)
    if snapshot.oldest_due_at is None:
        return timedelta(0)
    return max(now - snapshot.oldest_due_at, timedelta(0))


def error_ratio(snapshot: QueueSnapshot) -> float:
    """Share of the window's outcomes that never reached Telegram.

    An empty window is zero rather than one, for the reason tech.md 23.2.6
    gives about completion: nothing was sent, not everything failed.
    """
    total = snapshot.delivered + snapshot.failed
    if total <= 0:
        return 0.0
    return snapshot.failed / total


def build_report(snapshot: QueueSnapshot, now: datetime) -> OpsReport:
    return OpsReport(
        taken_at=now,
        queue_size=snapshot.due_deliveries,
        lag=queue_lag(snapshot, now),
        error_ratio=error_ratio(snapshot),
    )


def stale_after(beat: CycleBeat) -> timedelta:
    return timedelta(
        seconds=max(beat.interval_seconds * HEALTH_STALE_FACTOR, HEALTH_STALE_FLOOR_SECONDS)
    )


def is_stale(beat: CycleBeat, now: datetime) -> bool:
    _require_aware(now)
    return now - beat.last_tick_at > stale_after(beat)


def health_status(beats: Iterable[CycleBeat], now: datetime) -> HealthStatus:
    """`STALE` when any cycle stopped turning.

    An empty set is healthy: a worker that has not registered a cycle yet is
    not ill, it has not started.
    """
    if any(is_stale(beat, now) for beat in beats):
        return HealthStatus.STALE
    return HealthStatus.OK


def decide_alert(state: AlertState, lag: timedelta, threshold: timedelta) -> AlertDecision:
    """Next alert state and the message that edge owes, if any.

    The comparison is strict, like the TTL boundary of tech.md 20.3.2: a lag of
    exactly the threshold has not crossed it yet. Two calls in the same state
    notify at most once, which is what makes the cycle idempotent.
    """
    firing = lag > threshold
    if firing and state is AlertState.CLEAR:
        return AlertDecision(state=AlertState.FIRING, notify=AlertKind.RAISED)
    if not firing and state is AlertState.FIRING:
        return AlertDecision(state=AlertState.CLEAR, notify=AlertKind.CLEARED)
    return AlertDecision(state=state)


def _require_aware(moment: datetime) -> None:
    if moment.tzinfo is None:
        raise ValueError("moment must be timezone-aware")
