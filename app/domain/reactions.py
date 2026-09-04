"""Pure reaction decisions (tech.md 7.4).

The service owns the row lock, the transaction and the message. Every decision
about whether a tap counts and what it writes lives here, so the idempotency
rule is checked by property tests instead of by a database and a fake gateway.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Final

from app.domain.contracts import (
    TERMINAL_DELIVERY_STATUSES,
    TERMINAL_OCCURRENCE_STATUSES,
    ActionKind,
    DeliveryStatus,
    OccurrenceStatus,
)

#: Reactions a recipient can press. `auto_expire` belongs to the reaper.
USER_ACTIONS: Final[tuple[ActionKind, ...]] = (
    ActionKind.DONE,
    ActionKind.SNOOZE,
    ActionKind.SKIP,
)


class RejectReason(StrEnum):
    """Why a tap changes nothing.

    A rejection is an answer, not a failure: the user pressed a button that is
    still on screen but no longer means anything.
    """

    ALREADY_HANDLED = "already_handled"
    EXPIRED = "expired"


@dataclass(frozen=True, slots=True)
class Reaction:
    """What the service writes back for one accepted tap.

    `reacted_at` and `snoozed_until` are mutually exclusive: a postponed
    delivery is not answered yet, and an answered one is never redelivered.
    """

    kind: ActionKind
    status: DeliveryStatus
    reacted_at: datetime | None = None
    snoozed_until: datetime | None = None

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_DELIVERY_STATUSES


_TERMINAL_STATUS: Final[dict[ActionKind, DeliveryStatus]] = {
    ActionKind.DONE: DeliveryStatus.DONE,
    ActionKind.SKIP: DeliveryStatus.SKIPPED,
}

_OCCURRENCE_ROLLUP: Final[dict[ActionKind, OccurrenceStatus]] = {
    ActionKind.DONE: OccurrenceStatus.DONE,
    ActionKind.SKIP: OccurrenceStatus.SKIPPED,
}


def check_reactable(
    kind: ActionKind,
    *,
    delivery_status: DeliveryStatus,
    occurrence_status: OccurrenceStatus,
    expires_at: datetime,
    snoozed_until: datetime | None,
    now: datetime,
) -> RejectReason | None:
    """Reason this tap changes nothing, or `None` when it may be applied.

    Delivery is at-least-once (tech.md 7.2), so the same delivery can carry
    live buttons in more than one message. Rejecting by state rather than by
    message is what keeps the second tap from writing a second action.
    """
    if delivery_status in TERMINAL_DELIVERY_STATUSES:
        return RejectReason.ALREADY_HANDLED
    if occurrence_status in TERMINAL_OCCURRENCE_STATUSES or expires_at <= now:
        # Only `expired` is reachable in practice: a done or skipped occurrence
        # implies every delivery is terminal, and the branch above caught this
        # one already.
        return RejectReason.EXPIRED
    if kind is ActionKind.SNOOZE and is_postponed(delivery_status, snoozed_until, now):
        # Postponing an already postponed delivery is one stale button pressed
        # twice. Accepting it would push the redelivery further away each time.
        return RejectReason.ALREADY_HANDLED
    return None


def is_postponed(
    delivery_status: DeliveryStatus, snoozed_until: datetime | None, now: datetime
) -> bool:
    """Delivery is waiting out a snooze that has not run out yet."""
    return (
        delivery_status is DeliveryStatus.SNOOZED
        and snoozed_until is not None
        and snoozed_until > now
    )


def decide_reaction(kind: ActionKind, now: datetime, snooze_minutes: int) -> Reaction:
    """What an accepted tap writes to the delivery row."""
    if kind is ActionKind.SNOOZE:
        if snooze_minutes < 1:
            # A snooze into the past or the present is redelivered by the very
            # next dispatcher cycle, which is a loop rather than a postponement.
            raise ValueError("snooze_minutes must be at least one minute")
        return Reaction(
            kind=kind,
            status=DeliveryStatus.SNOOZED,
            snoozed_until=now + timedelta(minutes=snooze_minutes),
        )
    status = _TERMINAL_STATUS.get(kind)
    if status is None:
        raise ValueError(f"{kind.value} is not a reaction a recipient can press")
    return Reaction(kind=kind, status=status, reacted_at=now)


def roll_up_occurrence(
    kind: ActionKind, *, every_delivery_terminal: bool
) -> OccurrenceStatus | None:
    """Status the occurrence takes once its last recipient has answered.

    `None` means the occurrence stays as it is: a shared reminder is only
    closed by the recipient who answers last (tech.md 7.4).
    """
    if not every_delivery_terminal:
        return None
    return _OCCURRENCE_ROLLUP.get(kind)
