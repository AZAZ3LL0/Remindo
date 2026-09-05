"""The reaper's seam: the message it edits, and the queue it hands back.

Expiring a reminder is the one place the reaper talks to Telegram, and a repeat
is the one place a delivery re-enters the queue without a user asking for it.
Both are checked here against the contracts, without a database.
"""

from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.bot.render.texts import T
from app.domain.contracts import (
    TERMINAL_OCCURRENCE_STATUSES,
    ActionKind,
    OccurrenceStatus,
)
from app.domain.dispatching import AbortReason, check_deliverable
from app.domain.quiet_hours import QuietHours
from app.domain.reactions import USER_ACTIONS
from app.domain.sweeping import decide_repeat
from app.gateways.bot_gateway import OutgoingMessage
from app.gateways.fakes import validate_outgoing

NOW = datetime(2026, 6, 1, 20, 0, tzinfo=UTC)
MOSCOW_NIGHT = QuietHours(tz=ZoneInfo("Europe/Moscow"), start=time(22, 0), end=time(7, 0))

#: Largest id Postgres BIGSERIAL can hand a chat.
MAX_CHAT_ID = 2**63 - 1


@pytest.mark.parametrize("lang", ["ru", "en"])
def test_the_expired_message_satisfies_the_outgoing_contract(lang):
    """Exactly what `ReaperService` edits an expired reminder into.

    The keyboard is dropped rather than replaced: the delivery is closed, so
    any button left behind would only earn the user a rejection.
    """
    validate_outgoing(
        OutgoingMessage(chat_id=MAX_CHAT_ID, text=T("react.expired", lang), keyboard=None)
    )


def test_the_reapers_action_is_not_one_a_recipient_can_press():
    assert ActionKind.AUTO_EXPIRE not in USER_ACTIONS


def test_a_repeat_hands_the_queue_a_moment_it_can_compare():
    """`claim_due` compares `next_attempt_at` against an aware `now` (tech.md 7.2).

    A naive moment would raise inside the driver rather than fail a rule, which
    is why the type is pinned here and not only in the service.
    """
    plan = decide_repeat(
        sent_at=NOW - timedelta(hours=1),
        repeat_after_minutes=30,
        repeats_sent=0,
        max_repeats=2,
        expires_at=NOW + timedelta(hours=12),
        quiet=MOSCOW_NIGHT,
        now=NOW,
    )

    assert plan is not None
    assert plan.next_attempt_at.utcoffset() is not None
    assert plan.next_attempt_at > NOW


def test_the_two_halves_of_the_lifecycle_agree_on_what_expired_means():
    """The reaper closes an occurrence; the dispatcher must refuse to send it."""
    assert OccurrenceStatus.EXPIRED in TERMINAL_OCCURRENCE_STATUSES
    assert (
        check_deliverable(OccurrenceStatus.EXPIRED, user_blocked=False)
        is AbortReason.OCCURRENCE_CLOSED
    )
