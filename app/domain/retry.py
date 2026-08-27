"""Delivery retry policy (tech.md 7.2). Pure, clock-free."""

from datetime import datetime, timedelta

from app.domain.contracts import ErrorClass

BASE_BACKOFF = timedelta(seconds=30)
MAX_BACKOFF = timedelta(minutes=30)
MAX_ATTEMPTS = 5

#: Failures that never get another attempt.
FATAL_ERRORS = frozenset({ErrorClass.FORBIDDEN, ErrorClass.BAD_REQUEST})


def should_retry(attempts: int, error_class: ErrorClass) -> bool:
    if error_class in FATAL_ERRORS:
        return False
    if error_class is ErrorClass.RETRY_AFTER:
        # Flood control is not the delivery's fault, so it never burns the budget.
        return True
    return attempts < MAX_ATTEMPTS


def next_attempt(
    attempts: int,
    error_class: ErrorClass,
    now: datetime,
    retry_after: int | None = None,
) -> datetime:
    """Moment of the next delivery attempt.

    `attempts` is the counter after the failed attempt was claimed, so the first
    failure arrives here as 1.
    """
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    if error_class in FATAL_ERRORS:
        raise ValueError(f"{error_class} is fatal and has no next attempt")

    if error_class is ErrorClass.RETRY_AFTER:
        return now + timedelta(seconds=max(retry_after or 0, 0) + 1)

    # The cap keeps absurd attempt counters from overflowing timedelta.
    exponent = min(max(attempts, 1) - 1, 16)
    delay: timedelta = min(BASE_BACKOFF * (2**exponent), MAX_BACKOFF)
    return now + delay
