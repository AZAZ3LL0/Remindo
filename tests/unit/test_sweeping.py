"""Reaper rules of tech.md 7.3 as invariants, not as branches.

The acceptance criteria of S8 are that an unanswered reminder comes back
exactly `max_repeats` times, that it never comes back into the silence the user
configured, and that an answered occurrence is never expired underneath them.
"""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.domain.contracts import TERMINAL_OCCURRENCE_STATUSES, OccurrenceStatus
from app.domain.quiet_hours import QuietHours
from app.domain.sweeping import decide_repeat, is_overdue
from tests.unit.strategies import quiet_hours, silent_hours, utc_moments

CASES = settings(max_examples=200, deadline=None)

NO_SILENCE = QuietHours(tz=ZoneInfo("UTC"))

occurrence_statuses = st.sampled_from(list(OccurrenceStatus))
open_statuses = st.sampled_from(
    [status for status in OccurrenceStatus if status not in TERMINAL_OCCURRENCE_STATUSES]
)
spans = st.integers(min_value=1, max_value=10_000).map(lambda value: timedelta(minutes=value))
repeat_after = st.integers(min_value=1, max_value=1440)
budgets = st.integers(min_value=0, max_value=5)


def repeat(
    *,
    now,
    sent_ago=timedelta(hours=1),
    repeat_after_minutes=30,
    repeats_sent=0,
    max_repeats=2,
    ttl=timedelta(hours=3),
    quiet=NO_SILENCE,
):
    return decide_repeat(
        sent_at=now - sent_ago,
        repeat_after_minutes=repeat_after_minutes,
        repeats_sent=repeats_sent,
        max_repeats=max_repeats,
        expires_at=now + ttl,
        quiet=quiet,
        now=now,
    )


@CASES
@given(status=occurrence_statuses, now=utc_moments, ahead=spans)
def test_only_an_unanswered_occurrence_ever_expires(status, now, ahead):
    """Expiring a done occurrence would overwrite an answer with silence."""
    overdue = is_overdue(status, now - ahead, now)

    assert overdue is (status not in TERMINAL_OCCURRENCE_STATUSES)
    assert not is_overdue(status, now + ahead, now)


@CASES
@given(status=open_statuses, now=utc_moments)
def test_the_ttl_boundary_is_crossed_strictly(status, now):
    """The occurrence is swept once the TTL has passed, not as it runs out."""
    assert not is_overdue(status, now, now)
    assert is_overdue(status, now - timedelta(seconds=1), now)


@CASES
@given(now=utc_moments, repeats_sent=budgets, max_repeats=budgets)
def test_the_repeat_budget_is_never_overdrawn(now, repeats_sent, max_repeats):
    plan = repeat(now=now, repeats_sent=repeats_sent, max_repeats=max_repeats)

    assert (plan is not None) is (repeats_sent < max_repeats)


@CASES
@given(now=utc_moments, minutes=repeat_after, waited=spans)
def test_a_reminder_is_repeated_only_after_the_configured_delay(now, minutes, waited):
    plan = repeat(now=now, sent_ago=waited, repeat_after_minutes=minutes, ttl=timedelta(days=30))

    assert (plan is not None) is (waited >= timedelta(minutes=minutes))


@CASES
@given(now=utc_moments)
def test_a_reminder_without_a_repeat_delay_never_comes_back(now):
    assert repeat(now=now, repeat_after_minutes=None) is None


@CASES
@given(now=utc_moments, quiet=quiet_hours, ttl=spans)
def test_a_repeat_never_lands_inside_the_silence_or_past_the_expiry(now, quiet, ttl):
    """A repeat is a delivery, so the same silence applies to it."""
    plan = repeat(now=now, quiet=quiet, ttl=ttl)
    if plan is None:
        return

    assert plan.next_attempt_at >= now
    assert plan.next_attempt_at < now + ttl
    assert not quiet.covers(plan.next_attempt_at)


@CASES
@given(now=utc_moments, quiet=silent_hours, ttl=spans)
def test_silence_that_outlasts_the_occurrence_drops_the_repeat(now, quiet, ttl):
    """Better no second message than one whose buttons are dead on arrival."""
    plan = repeat(now=now, quiet=quiet, ttl=ttl)

    if quiet.shift(now) >= now + ttl:
        assert plan is None


@CASES
@given(now=utc_moments, quiet=quiet_hours, ttl=spans, repeats_sent=budgets)
def test_deciding_twice_decides_the_same(now, quiet, ttl, repeats_sent):
    first = repeat(now=now, quiet=quiet, ttl=ttl, repeats_sent=repeats_sent)
    second = repeat(now=now, quiet=quiet, ttl=ttl, repeats_sent=repeats_sent)

    assert first == second


def test_a_delivery_that_never_went_out_is_not_repeated():
    """`sent_at` is empty until the dispatcher succeeds."""
    now = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
    assert (
        decide_repeat(
            sent_at=None,
            repeat_after_minutes=30,
            repeats_sent=0,
            max_repeats=2,
            expires_at=now + timedelta(hours=3),
            quiet=NO_SILENCE,
            now=now,
        )
        is None
    )


def test_a_naive_moment_is_refused():
    with pytest.raises(ValueError, match="timezone-aware"):
        decide_repeat(
            sent_at=None,
            repeat_after_minutes=30,
            repeats_sent=0,
            max_repeats=2,
            expires_at=datetime(2026, 6, 1, 15, 0, tzinfo=UTC),
            quiet=NO_SILENCE,
            now=datetime(2026, 6, 1, 12, 0),
        )
