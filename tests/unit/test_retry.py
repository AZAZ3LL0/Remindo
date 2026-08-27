"""Retry policy table from tech.md 7.2."""

from datetime import UTC, datetime, timedelta

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.domain.contracts import ErrorClass
from app.domain.retry import (
    BASE_BACKOFF,
    MAX_ATTEMPTS,
    MAX_BACKOFF,
    next_attempt,
    should_retry,
)

NOW = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
CASES = settings(max_examples=200, deadline=None)


@CASES
@given(attempts=st.integers(min_value=1, max_value=50))
def test_transient_backoff_stays_inside_the_bounds(attempts):
    delay = next_attempt(attempts, ErrorClass.TRANSIENT, NOW) - NOW
    assert BASE_BACKOFF <= delay <= MAX_BACKOFF


@CASES
@given(attempts=st.integers(min_value=1, max_value=50))
def test_transient_backoff_never_shrinks(attempts):
    earlier = next_attempt(attempts, ErrorClass.TRANSIENT, NOW)
    later = next_attempt(attempts + 1, ErrorClass.TRANSIENT, NOW)
    assert later >= earlier


@CASES
@given(
    attempts=st.integers(min_value=1, max_value=50),
    retry_after=st.integers(min_value=0, max_value=3600),
)
def test_retry_after_is_honoured_exactly(attempts, retry_after):
    """Flood control dictates the delay; the attempt counter does not."""
    moment = next_attempt(attempts, ErrorClass.RETRY_AFTER, NOW, retry_after=retry_after)
    assert moment == NOW + timedelta(seconds=retry_after + 1)


@CASES
@given(attempts=st.integers(min_value=1, max_value=100))
def test_retry_after_never_exhausts_the_budget(attempts):
    assert should_retry(attempts, ErrorClass.RETRY_AFTER)


def test_transient_gives_up_after_the_attempt_budget():
    assert should_retry(MAX_ATTEMPTS - 1, ErrorClass.TRANSIENT)
    assert not should_retry(MAX_ATTEMPTS, ErrorClass.TRANSIENT)


@pytest.mark.parametrize("error_class", [ErrorClass.FORBIDDEN, ErrorClass.BAD_REQUEST])
def test_fatal_errors_have_no_next_attempt(error_class):
    assert not should_retry(1, error_class)
    with pytest.raises(ValueError, match="fatal"):
        next_attempt(1, error_class, NOW)


def test_backoff_doubles_from_thirty_seconds():
    delays = [next_attempt(attempts, ErrorClass.TRANSIENT, NOW) - NOW for attempts in range(1, 6)]
    assert delays == [
        timedelta(seconds=30),
        timedelta(minutes=1),
        timedelta(minutes=2),
        timedelta(minutes=4),
        timedelta(minutes=8),
    ]


def test_naive_now_is_rejected():
    with pytest.raises(ValueError, match="timezone-aware"):
        next_attempt(1, ErrorClass.TRANSIENT, datetime(2026, 6, 1, 12, 0))
