"""Dispatcher verdicts: the error table of tech.md 7.2 as rules, not branches."""

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.domain.contracts import (
    TERMINAL_DELIVERY_STATUSES,
    TERMINAL_OCCURRENCE_STATUSES,
    DeliveryStatus,
    ErrorClass,
    OccurrenceStatus,
)
from app.domain.dispatching import (
    AbortReason,
    check_deliverable,
    decide_abort,
    decide_failure,
    decide_success,
)
from app.domain.retry import BASE_BACKOFF, MAX_ATTEMPTS, MAX_BACKOFF
from tests.unit.strategies import utc_moments

CASES = settings(max_examples=200, deadline=None)

attempt_counts = st.integers(min_value=1, max_value=50)
error_classes = st.sampled_from(list(ErrorClass))
occurrence_statuses = st.sampled_from(list(OccurrenceStatus))
abort_reasons = st.sampled_from(list(AbortReason))
FATAL = (ErrorClass.FORBIDDEN, ErrorClass.BAD_REQUEST)


@CASES
@given(attempts=attempt_counts, error_class=error_classes, now=utc_moments)
def test_a_verdict_either_retries_or_ends_the_delivery(attempts, error_class, now):
    verdict = decide_failure(attempts, error_class, now, error_code="Boom")

    if verdict.is_retry:
        assert verdict.status is DeliveryStatus.PENDING
        assert verdict.next_attempt_at > now
    else:
        assert verdict.status in TERMINAL_DELIVERY_STATUSES
        assert verdict.next_attempt_at is None


@CASES
@given(attempts=attempt_counts, error_class=error_classes, now=utc_moments)
def test_a_failed_attempt_is_never_charged_twice(attempts, error_class, now):
    """The claim already charged one attempt; a verdict may refund, never add."""
    verdict = decide_failure(attempts, error_class, now, error_code="Boom")

    assert verdict.attempts <= attempts


@CASES
@given(attempts=attempt_counts, error_class=error_classes, now=utc_moments)
def test_every_failure_records_why(attempts, error_class, now):
    assert decide_failure(attempts, error_class, now, error_code="Boom").error_code == "Boom"


@CASES
@given(attempts=attempt_counts, error_class=st.sampled_from(FATAL), now=utc_moments)
def test_a_fatal_error_never_gets_another_attempt(attempts, error_class, now):
    verdict = decide_failure(attempts, error_class, now, error_code="Boom")

    assert not verdict.is_retry
    assert verdict.blocks_user is (error_class is ErrorClass.FORBIDDEN)


@CASES
@given(attempts=attempt_counts, error_class=error_classes, now=utc_moments)
def test_only_a_forbidden_error_blocks_the_user(attempts, error_class, now):
    verdict = decide_failure(attempts, error_class, now, error_code="Boom")

    assert verdict.blocks_user is (error_class is ErrorClass.FORBIDDEN)
    if verdict.blocks_user:
        assert verdict.status is DeliveryStatus.BLOCKED


@CASES
@given(
    attempts=attempt_counts,
    retry_after=st.integers(min_value=0, max_value=3600),
    now=utc_moments,
)
def test_flood_control_reschedules_without_spending_the_budget(attempts, retry_after, now):
    verdict = decide_failure(
        attempts,
        ErrorClass.RETRY_AFTER,
        now,
        error_code="TelegramRetryAfter",
        retry_after=retry_after,
    )

    assert verdict.is_retry
    assert verdict.attempts == attempts - 1
    assert (verdict.next_attempt_at - now).total_seconds() == retry_after + 1


@CASES
@given(attempts=attempt_counts, now=utc_moments)
def test_a_transient_failure_retries_until_the_budget_runs_out(attempts, now):
    verdict = decide_failure(attempts, ErrorClass.TRANSIENT, now, error_code="TimeoutError")

    assert verdict.is_retry is (attempts < MAX_ATTEMPTS)
    if verdict.is_retry:
        assert BASE_BACKOFF <= verdict.next_attempt_at - now <= MAX_BACKOFF
        # A transport failure spends the attempt it was charged.
        assert verdict.attempts == attempts
    else:
        assert verdict.status is DeliveryStatus.FAILED


@CASES
@given(attempts=attempt_counts, error_class=error_classes, now=utc_moments)
def test_the_same_failure_always_gets_the_same_verdict(attempts, error_class, now):
    kwargs = {"error_code": "Boom", "retry_after": 7}
    assert decide_failure(attempts, error_class, now, **kwargs) == decide_failure(
        attempts, error_class, now, **kwargs
    )


def test_a_delivered_message_clears_the_budget_it_spent():
    verdict = decide_success()

    assert verdict.status is DeliveryStatus.SENT
    assert verdict.attempts == 0
    assert verdict.error_code is None
    assert not verdict.is_retry


@CASES
@given(status=occurrence_statuses, user_blocked=st.booleans())
def test_a_closed_occurrence_or_a_blocked_user_stops_the_send(status, user_blocked):
    reason = check_deliverable(status, user_blocked=user_blocked)

    if status in TERMINAL_OCCURRENCE_STATUSES:
        assert reason is AbortReason.OCCURRENCE_CLOSED
    elif user_blocked:
        assert reason is AbortReason.USER_BLOCKED
    else:
        assert reason is None


@CASES
@given(reason=abort_reasons, attempts=attempt_counts)
def test_an_aborted_send_ends_the_delivery_and_refunds_the_attempt(reason, attempts):
    verdict = decide_abort(reason, attempts)

    assert verdict.status in TERMINAL_DELIVERY_STATUSES
    assert not verdict.is_retry
    # Telegram was never called, so the claim's charge is given back.
    assert verdict.attempts == attempts - 1
    assert verdict.error_code == reason.value


@pytest.mark.parametrize(
    ("reason", "status"),
    [
        (AbortReason.USER_BLOCKED, DeliveryStatus.BLOCKED),
        (AbortReason.OCCURRENCE_CLOSED, DeliveryStatus.FAILED),
        (AbortReason.CONTEXT_MISSING, DeliveryStatus.FAILED),
    ],
)
def test_an_abort_reason_maps_to_its_status(reason, status):
    verdict = decide_abort(reason, attempts=1)

    assert verdict.status is status
    # The user is already flagged; the abort must not flag them a second time.
    assert verdict.blocks_user is False
