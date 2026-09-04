"""The reaction seam: the buttons that go out and the message that replaces them.

A reaction answers a message the dispatcher rendered, so the redrawn message
has to satisfy the same outgoing contract the original did (tech.md 8), minus
the keyboard: after a reaction there is nothing left to press.
"""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from app.bot.callbacks import ReactCb
from app.bot.keyboards.actions import reminder_actions_kb
from app.bot.render.reactions import render_outcome, render_reacted_message
from app.bot.render.reminder import render_reminder_message
from app.bot.render.texts import SUPPORTED_LANGS, TEXTS
from app.db.models import Category, Reminder
from app.domain.contracts import REMINDER_TITLE_MAX_LENGTH, ActionKind, DeliveryStatus
from app.domain.reactions import USER_ACTIONS, RejectReason
from app.gateways.bot_gateway import OutgoingMessage
from app.gateways.fakes import validate_keyboard, validate_outgoing
from app.services.reactions import ACTION_KINDS, ReactionResult

FIRE_AT = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
SNOOZED_UNTIL = datetime(2026, 6, 1, 12, 10, tzinfo=UTC)
TZ = ZoneInfo("Australia/Lord_Howe")
#: Largest id Postgres BIGSERIAL can hand a delivery.
MAX_DELIVERY_ID = 2**63 - 1

LANGS = list(SUPPORTED_LANGS)

APPLIED = [
    ReactionResult(applied=True, kind=ActionKind.DONE, status=DeliveryStatus.DONE),
    ReactionResult(applied=True, kind=ActionKind.SKIP, status=DeliveryStatus.SKIPPED),
    ReactionResult(
        applied=True,
        kind=ActionKind.SNOOZE,
        status=DeliveryStatus.SNOOZED,
        snoozed_until=SNOOZED_UNTIL,
    ),
]

REJECTED = [
    ReactionResult(applied=False, kind=ActionKind.DONE, status=DeliveryStatus.DONE, reason=reason)
    for reason in RejectReason
]

RESULTS = APPLIED + REJECTED


def case_id(result: ReactionResult) -> str:
    return result.reason.value if result.reason is not None else result.kind.value


def longest_reminder_message(lang: str) -> str:
    """The longest reminder a user can create, as the dispatcher renders it."""
    reminder = Reminder(title="я" * REMINDER_TITLE_MAX_LENGTH, snooze_minutes=10)
    category = Category(code="water", title="Вода", emoji="💧")
    return render_reminder_message(reminder, category, FIRE_AT, TZ, lang)


@pytest.mark.parametrize("lang", LANGS)
@pytest.mark.parametrize("result", RESULTS, ids=case_id)
def test_the_redrawn_message_satisfies_the_outgoing_contract(result, lang):
    text = render_reacted_message(longest_reminder_message(lang), render_outcome(result, TZ, lang))

    validate_outgoing(OutgoingMessage(chat_id=MAX_DELIVERY_ID, text=text, keyboard=None))


@pytest.mark.parametrize("lang", LANGS)
@pytest.mark.parametrize("result", RESULTS, ids=case_id)
def test_the_reminder_survives_its_own_answer(result, lang):
    """The answer is appended, never substituted: the user sees what they answered."""
    body = longest_reminder_message(lang)
    outcome = render_outcome(result, TZ, lang)

    redrawn = render_reacted_message(body, outcome)

    assert redrawn.startswith(body)
    assert redrawn.endswith(outcome)
    assert outcome.strip()


@pytest.mark.parametrize("lang", LANGS)
def test_a_message_without_text_still_reports_the_outcome(lang):
    outcome = render_outcome(APPLIED[0], TZ, lang)

    assert render_reacted_message("", outcome) == outcome


@pytest.mark.parametrize("lang", LANGS)
def test_the_snooze_answer_names_the_moment_it_moved_to(lang):
    outcome = render_outcome(APPLIED[2], TZ, lang)

    assert SNOOZED_UNTIL.astimezone(TZ).strftime("%H:%M") in outcome


@pytest.mark.parametrize("lang", LANGS)
def test_the_reaction_keyboard_is_accepted_by_the_gateway(lang):
    """Every button the user can press unpacks with the frozen factory."""
    keyboard = reminder_actions_kb(MAX_DELIVERY_ID, 10, lang)

    validate_keyboard(keyboard)
    buttons = [button for row in keyboard.inline_keyboard for button in row]
    assert {ReactCb.unpack(button.callback_data).action for button in buttons} == set(ACTION_KINDS)


def test_every_button_maps_onto_a_reaction_the_domain_knows():
    """The callback contract of tech.md 6 and the action enum of 4.1 agree."""
    assert set(ACTION_KINDS.values()) == set(USER_ACTIONS)
    assert set(ACTION_KINDS) == set(ReactCb.model_fields["action"].annotation.__args__)


@pytest.mark.parametrize("key", ["react.done", "react.skipped", "react.snoozed", "react.already"])
def test_every_outcome_is_translated_into_both_locales(key):
    assert set(TEXTS[key]) == set(SUPPORTED_LANGS)


def test_every_rejection_has_something_to_say():
    """A refused tap answers the user; it never leaves the query hanging."""
    for reason in RejectReason:
        result = ReactionResult(
            applied=False, kind=ActionKind.DONE, status=DeliveryStatus.DONE, reason=reason
        )
        for lang in SUPPORTED_LANGS:
            assert render_outcome(result, TZ, lang).strip()
