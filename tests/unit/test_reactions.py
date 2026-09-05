"""Reaction rules of tech.md 7.4 as invariants, not as branches.

The acceptance criterion of S6 is that pressing a button twice has one effect.
Stated purely, that is: whatever a tap writes, the state it leaves behind
refuses the same tap.
"""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.domain.contracts import (
    TERMINAL_DELIVERY_STATUSES,
    TERMINAL_OCCURRENCE_STATUSES,
    ActionKind,
    DeliveryStatus,
    OccurrenceStatus,
)
from app.domain.quiet_hours import QuietHours
from app.domain.reactions import (
    USER_ACTIONS,
    RejectReason,
    check_reactable,
    decide_reaction,
    postpone,
    roll_up_occurrence,
)
from tests.unit.strategies import quiet_hours, silent_hours, utc_moments

CASES = settings(max_examples=200, deadline=None)

#: A fixed moment for the rules that do not depend on when they are checked.
NOW = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)

user_actions = st.sampled_from(USER_ACTIONS)
delivery_statuses = st.sampled_from(list(DeliveryStatus))
occurrence_statuses = st.sampled_from(list(OccurrenceStatus))
open_occurrence_statuses = st.sampled_from(
    [status for status in OccurrenceStatus if status not in TERMINAL_OCCURRENCE_STATUSES]
)
live_delivery_statuses = st.sampled_from(
    [status for status in DeliveryStatus if status not in TERMINAL_DELIVERY_STATUSES]
)
snooze_minutes = st.integers(min_value=1, max_value=1440)
horizons = st.integers(min_value=1, max_value=10_000).map(lambda value: timedelta(minutes=value))


#: Silence switched off, the state a reaction test is in unless it says otherwise.
NO_SILENCE = QuietHours(tz=ZoneInfo("UTC"))

#: Far enough out that the TTL never caps a snooze the test did not aim at it.
FOREVER = timedelta(days=365)


def decide(kind, now, minutes, *, quiet=NO_SILENCE, expires_at=None):
    return decide_reaction(kind, now, minutes, quiet=quiet, expires_at=expires_at or now + FOREVER)


def check(kind, now, *, delivery_status, occurrence_status, expires_at, snoozed_until=None):
    return check_reactable(
        kind,
        delivery_status=delivery_status,
        occurrence_status=occurrence_status,
        expires_at=expires_at,
        snoozed_until=snoozed_until,
        now=now,
    )


@CASES
@given(
    kind=user_actions,
    delivery_status=st.sampled_from(sorted(TERMINAL_DELIVERY_STATUSES)),
    occurrence_status=occurrence_statuses,
    now=utc_moments,
    ahead=horizons,
)
def test_an_answered_delivery_never_accepts_another_reaction(
    kind, delivery_status, occurrence_status, now, ahead
):
    reason = check(
        kind,
        now,
        delivery_status=delivery_status,
        occurrence_status=occurrence_status,
        expires_at=now + ahead,
    )

    assert reason is RejectReason.ALREADY_HANDLED


@CASES
@given(
    kind=user_actions,
    delivery_status=live_delivery_statuses,
    now=utc_moments,
    behind=horizons,
)
def test_an_expired_occurrence_refuses_every_reaction(kind, delivery_status, now, behind):
    """Past the deadline the buttons are dead, whatever the delivery says."""
    reason = check(
        kind,
        now,
        delivery_status=delivery_status,
        occurrence_status=OccurrenceStatus.SENT,
        expires_at=now - behind,
    )

    assert reason is RejectReason.EXPIRED


@CASES
@given(
    kind=user_actions,
    delivery_status=live_delivery_statuses,
    occurrence_status=open_occurrence_statuses,
    now=utc_moments,
    ahead=horizons,
    minutes=snooze_minutes,
)
def test_a_reaction_leaves_a_state_that_refuses_the_same_reaction(
    kind, delivery_status, occurrence_status, now, ahead, minutes
):
    """The idempotency rule of S6, stated without a database."""
    reason = check(
        kind,
        now,
        delivery_status=delivery_status,
        occurrence_status=occurrence_status,
        expires_at=now + ahead,
        snoozed_until=None,
    )
    # A live delivery under an open occurrence always takes a first tap.
    assert reason is None

    reaction = decide(kind, now, minutes)
    repeated = check(
        kind,
        now,
        delivery_status=reaction.status,
        occurrence_status=occurrence_status,
        expires_at=now + ahead,
        snoozed_until=reaction.snoozed_until,
    )

    assert repeated is RejectReason.ALREADY_HANDLED


@CASES
@given(now=utc_moments, ahead=horizons, minutes=snooze_minutes)
def test_a_postponed_delivery_still_takes_a_final_answer(now, ahead, minutes):
    """Snoozing is not answering: a duplicate message may still close it."""
    snoozed = decide(ActionKind.SNOOZE, now, minutes)

    for kind in (ActionKind.DONE, ActionKind.SKIP):
        assert (
            check(
                kind,
                now,
                delivery_status=snoozed.status,
                occurrence_status=OccurrenceStatus.SENT,
                expires_at=now + ahead + timedelta(minutes=minutes),
                snoozed_until=snoozed.snoozed_until,
            )
            is None
        )


@CASES
@given(kind=user_actions, now=utc_moments, minutes=snooze_minutes)
def test_a_reaction_writes_a_due_moment_or_an_answer_but_never_both(kind, now, minutes):
    reaction = decide(kind, now, minutes)

    assert (reaction.reacted_at is None) != (reaction.snoozed_until is None)
    assert reaction.kind is kind
    assert reaction.status in (DeliveryStatus.DONE, DeliveryStatus.SKIPPED, DeliveryStatus.SNOOZED)


@CASES
@given(now=utc_moments, minutes=snooze_minutes)
def test_a_snooze_always_lands_in_the_future(now, minutes):
    reaction = decide(ActionKind.SNOOZE, now, minutes)

    assert reaction.snoozed_until == now + timedelta(minutes=minutes)
    assert reaction.snoozed_until > now
    assert reaction.is_terminal is False


@CASES
@given(now=utc_moments, minutes=snooze_minutes, quiet=silent_hours, ahead=horizons)
def test_a_snooze_never_lands_inside_the_silence_it_can_escape(now, minutes, quiet, ahead):
    """Asking for ten more minutes at 22:55 must not answer at 23:05.

    The one moment allowed to stay silent is the requested one: the occurrence
    dies before the silence ends, so the reminder comes back late instead of
    never.
    """
    requested = now + timedelta(minutes=minutes)
    expires_at = requested + ahead
    reaction = decide(ActionKind.SNOOZE, now, minutes, quiet=quiet, expires_at=expires_at)

    assert reaction.snoozed_until >= requested
    assert not quiet.covers(reaction.snoozed_until) or reaction.snoozed_until == requested


@CASES
@given(now=utc_moments, minutes=snooze_minutes, quiet=quiet_hours, ahead=horizons)
def test_silence_that_outlasts_the_occurrence_never_swallows_the_snooze(now, minutes, quiet, ahead):
    """Late beats lost: a reminder is postponed, never dropped (tech.md 1.1)."""
    expires_at = now + timedelta(minutes=minutes) + ahead
    moment = postpone(now, minutes, quiet=quiet, expires_at=expires_at)

    assert moment < expires_at
    assert moment >= now + timedelta(minutes=minutes)


@CASES
@given(now=utc_moments, minutes=snooze_minutes, quiet=quiet_hours, ahead=horizons)
def test_postponing_twice_postpones_the_same(now, minutes, quiet, ahead):
    expires_at = now + timedelta(minutes=minutes) + ahead
    assert postpone(now, minutes, quiet=quiet, expires_at=expires_at) == postpone(
        now, minutes, quiet=quiet, expires_at=expires_at
    )


@CASES
@given(kind=user_actions, now=utc_moments, minutes=snooze_minutes)
def test_deciding_twice_decides_the_same(kind, now, minutes):
    assert decide(kind, now, minutes) == decide(kind, now, minutes)


@CASES
@given(kind=user_actions, closed=st.booleans())
def test_only_a_final_answer_from_the_last_recipient_closes_the_occurrence(kind, closed):
    status = roll_up_occurrence(kind, every_delivery_terminal=closed)

    if kind is ActionKind.SNOOZE or not closed:
        assert status is None
    else:
        assert status in TERMINAL_OCCURRENCE_STATUSES


@pytest.mark.parametrize(
    ("kind", "expected"),
    [(ActionKind.DONE, OccurrenceStatus.DONE), (ActionKind.SKIP, OccurrenceStatus.SKIPPED)],
)
def test_the_occurrence_follows_the_reaction_that_closed_it(kind, expected):
    assert roll_up_occurrence(kind, every_delivery_terminal=True) is expected


def test_the_reapers_action_is_not_a_reaction():
    """`auto_expire` is written by the reaper, never by a button."""
    assert ActionKind.AUTO_EXPIRE not in USER_ACTIONS
    with pytest.raises(ValueError, match="recipient"):
        decide(ActionKind.AUTO_EXPIRE, NOW, 10)


@pytest.mark.parametrize("minutes", [0, -1])
def test_a_snooze_shorter_than_a_minute_is_refused(minutes):
    """It would be redelivered by the next dispatcher cycle, in a loop."""
    with pytest.raises(ValueError, match="at least one minute"):
        decide(ActionKind.SNOOZE, NOW, minutes)
