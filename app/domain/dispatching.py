"""Pure dispatcher decisions: what one delivery attempt does to its row.

The service owns transactions, SQL and the network call. Every decision about
*which* status, budget and next attempt a delivery ends up with lives here, so
the error table of tech.md 7.2 is checked by property tests instead of by a
database and a fake gateway.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from app.domain.contracts import (
    TERMINAL_OCCURRENCE_STATUSES,
    DeliveryStatus,
    ErrorClass,
    OccurrenceStatus,
)
from app.domain.retry import next_attempt, should_retry


class AbortReason(StrEnum):
    """Why a claimed delivery is dropped before anything is sent."""

    #: The reaper expired the occurrence, or every recipient already answered.
    #: Its buttons are dead, so a message would only invite a rejected tap.
    OCCURRENCE_CLOSED = "occurrence_closed"
    #: The bot is already known to be blocked. Sending burns a flood budget
    #: that live recipients need; /start clears the flag when the user returns.
    USER_BLOCKED = "user_blocked"
    #: The row lost the reminder, category or user it points at.
    CONTEXT_MISSING = "context_missing"


@dataclass(frozen=True, slots=True)
class Verdict:
    """What the service writes back after one attempt.

    `attempts` is the counter the row keeps, not a delta: the claim charges an
    attempt up front, and only this verdict decides whether it stays charged.
    """

    status: DeliveryStatus
    attempts: int
    next_attempt_at: datetime | None = None
    error_code: str | None = None
    blocks_user: bool = False

    @property
    def is_retry(self) -> bool:
        return self.next_attempt_at is not None


def check_deliverable(
    occurrence_status: OccurrenceStatus, *, user_blocked: bool
) -> AbortReason | None:
    """Reason not to send at all, or `None` when the delivery may go out."""
    if occurrence_status in TERMINAL_OCCURRENCE_STATUSES:
        return AbortReason.OCCURRENCE_CLOSED
    if user_blocked:
        return AbortReason.USER_BLOCKED
    return None


def decide_abort(reason: AbortReason, attempts: int) -> Verdict:
    """Close a delivery that must not be sent. The attempt is refunded.

    Nothing was attempted against Telegram, so the claim's charge is given back
    and the row carries the reason instead of a transport error.
    """
    status = DeliveryStatus.BLOCKED if reason is AbortReason.USER_BLOCKED else DeliveryStatus.FAILED
    return Verdict(status=status, attempts=_refund(attempts), error_code=reason.value)


def decide_success() -> Verdict:
    """A delivered message clears the budget it spent getting through.

    Without the reset the counter would keep growing across snoozes and
    automatic repeats, and a single network blip on the sixth send of a healthy
    delivery would look like an exhausted budget.
    """
    return Verdict(status=DeliveryStatus.SENT, attempts=0)


def decide_failure(
    attempts: int,
    error_class: ErrorClass,
    now: datetime,
    error_code: str,
    retry_after: int | None = None,
) -> Verdict:
    """Apply the error table of tech.md 7.2 to a failed attempt."""
    if error_class is ErrorClass.FORBIDDEN:
        return Verdict(
            status=DeliveryStatus.BLOCKED,
            attempts=attempts,
            error_code=error_code,
            blocks_user=True,
        )

    if not should_retry(attempts, error_class):
        return Verdict(status=DeliveryStatus.FAILED, attempts=attempts, error_code=error_code)

    # Flood control is not this delivery's fault, so it does not burn the
    # budget: the claim already charged the attempt, and this gives it back.
    kept = _refund(attempts) if error_class is ErrorClass.RETRY_AFTER else attempts
    return Verdict(
        status=DeliveryStatus.PENDING,
        attempts=kept,
        next_attempt_at=next_attempt(attempts, error_class, now, retry_after=retry_after),
        error_code=error_code,
    )


def _refund(attempts: int) -> int:
    return max(attempts - 1, 0)
