"""Ops rules of tech.md 24 as invariants, not as branches.

The acceptance criteria of S12 are that an operator can trust the three
numbers, that a cycle which stopped turning is always noticed, and that the
alert speaks once per episode instead of once per minute.
"""

from datetime import datetime, timedelta

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.domain.contracts import HealthStatus, JobId
from app.domain.ops import (
    HEALTH_STALE_FLOOR_SECONDS,
    AlertKind,
    AlertState,
    CycleBeat,
    QueueSnapshot,
    build_report,
    decide_alert,
    error_ratio,
    health_status,
    is_stale,
    queue_lag,
    stale_after,
)
from tests.unit.strategies import utc_moments

CASES = settings(max_examples=200, deadline=None)

counts = st.integers(min_value=0, max_value=10_000)
spans = st.integers(min_value=0, max_value=100_000).map(lambda value: timedelta(seconds=value))
intervals = st.floats(min_value=0.1, max_value=3600, allow_nan=False, allow_infinity=False)
jobs = st.sampled_from(list(JobId))
alert_states = st.sampled_from(list(AlertState))


def beat(now, *, job=JobId.PLANNER_MATERIALIZE, interval=60.0, ago=timedelta(0), failures=0):
    return CycleBeat(job=job, interval_seconds=interval, last_tick_at=now - ago, failures=failures)


# --- the three numbers ------------------------------------------------------


@CASES
@given(now=utc_moments, ahead=spans, behind=spans, due=counts)
def test_lag_is_never_negative(now, ahead, behind, due):
    """A queue whose next attempt is in the future is on time, not early."""
    future = queue_lag(QueueSnapshot(due_deliveries=due, oldest_due_at=now + ahead), now)
    past = queue_lag(QueueSnapshot(due_deliveries=due, oldest_due_at=now - behind), now)

    assert future == timedelta(0)
    assert past == behind


@CASES
@given(now=utc_moments)
def test_an_empty_queue_lags_by_nothing(now):
    assert queue_lag(QueueSnapshot(), now) == timedelta(0)


@CASES
@given(delivered=counts, failed=counts)
def test_error_ratio_stays_a_share(delivered, failed):
    ratio = error_ratio(QueueSnapshot(delivered=delivered, failed=failed))

    assert 0.0 <= ratio <= 1.0
    assert (ratio == 1.0) is (delivered == 0 and failed > 0)


def test_an_empty_window_reports_no_errors_rather_than_all_of_them():
    """Nothing was sent, not everything failed (tech.md 24.2)."""
    assert error_ratio(QueueSnapshot()) == 0.0


@CASES
@given(now=utc_moments, behind=spans, due=counts, delivered=counts, failed=counts)
def test_the_report_carries_the_moment_it_was_read(now, behind, due, delivered, failed):
    snapshot = QueueSnapshot(
        due_deliveries=due,
        oldest_due_at=now - behind,
        delivered=delivered,
        failed=failed,
    )

    report = build_report(snapshot, now)

    assert report.taken_at == now
    assert report.queue_size == due
    assert report.lag == queue_lag(snapshot, now)
    assert report.error_ratio == error_ratio(snapshot)


def test_a_naive_moment_is_refused_rather_than_guessed_at():
    with pytest.raises(ValueError):
        queue_lag(QueueSnapshot(), datetime(2026, 6, 1, 12, 0))


# --- staleness --------------------------------------------------------------


@CASES
@given(now=utc_moments, interval=intervals, job=jobs)
def test_a_cycle_that_just_ticked_is_never_stale(now, interval, job):
    assert not is_stale(beat(now, job=job, interval=interval), now)


@CASES
@given(now=utc_moments, interval=intervals, extra=spans)
def test_staleness_only_ever_grows_with_time(now, interval, extra):
    """A cycle judged stale does not recover because the clock moved on."""
    one = beat(now, interval=interval)
    budget = stale_after(one)

    assert is_stale(one, now + budget) is False
    assert is_stale(one, now + budget + timedelta(seconds=1) + extra) is True


@CASES
@given(now=utc_moments, interval=intervals)
def test_the_budget_never_drops_below_the_floor(now, interval):
    """The dispatcher ticks every ten seconds; three of those is less than one
    planner tick, and a normal pause must not read as a failure."""
    budget = stale_after(beat(now, job=JobId.DISPATCHER_DELIVER, interval=interval))

    assert budget >= timedelta(seconds=HEALTH_STALE_FLOOR_SECONDS)


@CASES
@given(now=utc_moments, interval=intervals)
def test_one_stalled_cycle_makes_the_worker_unhealthy(now, interval):
    fresh = beat(now, job=JobId.PLANNER_MATERIALIZE, interval=interval)
    stalled = beat(
        now,
        job=JobId.DISPATCHER_DELIVER,
        interval=interval,
        ago=stale_after(fresh) + timedelta(seconds=1),
    )

    assert health_status([fresh], now) is HealthStatus.OK
    assert health_status([fresh, stalled], now) is HealthStatus.STALE


@CASES
@given(now=utc_moments)
def test_a_worker_with_no_cycles_yet_is_not_ill(now):
    """It has not started, which is a different thing from having stopped."""
    assert health_status([], now) is HealthStatus.OK


# --- the alert edge ---------------------------------------------------------


@CASES
@given(state=alert_states, lag=spans, threshold=spans)
def test_the_second_tick_in_the_same_state_says_nothing(state, lag, threshold):
    """This is what makes the cycle idempotent: two runs, one message."""
    first = decide_alert(state, lag, threshold)
    second = decide_alert(first.state, lag, threshold)

    assert second.notify is None
    assert second.state is first.state


@CASES
@given(state=alert_states, lag=spans, threshold=spans)
def test_a_notification_only_ever_accompanies_a_change_of_state(state, lag, threshold):
    decision = decide_alert(state, lag, threshold)

    assert (decision.notify is None) is (decision.state is state)


@CASES
@given(threshold=spans, over=spans)
def test_crossing_the_threshold_raises_and_falling_back_clears(threshold, over):
    above = threshold + over + timedelta(seconds=1)

    raised = decide_alert(AlertState.CLEAR, above, threshold)
    cleared = decide_alert(raised.state, threshold, threshold)

    assert raised.notify is AlertKind.RAISED
    assert cleared.notify is AlertKind.CLEARED
    assert cleared.state is AlertState.CLEAR


@CASES
@given(threshold=spans)
def test_a_lag_of_exactly_the_threshold_has_not_crossed_it(threshold):
    """Strict, like the TTL boundary of tech.md 20.3.2."""
    assert decide_alert(AlertState.CLEAR, threshold, threshold).notify is None
