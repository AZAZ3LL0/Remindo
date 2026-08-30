"""The dispatcher's two seams: what goes out, and how a failure comes back.

The gateway is where aiogram meets the domain vocabulary of tech.md 7.2, and
`FakeBotGateway` is where an outgoing message meets the Telegram limits.
"""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramNotFound,
    TelegramRetryAfter,
    TelegramServerError,
)

from app.bot.callbacks import ReactCb
from app.bot.keyboards.actions import reminder_actions_kb
from app.bot.render.reminder import render_reminder_message
from app.db.models import Category, Reminder
from app.domain.contracts import REMINDER_TITLE_MAX_LENGTH, ErrorClass, ReminderStatus
from app.gateways.bot_gateway import OutgoingMessage, classify_error, retry_after_seconds
from app.gateways.fakes import validate_outgoing

FIRE_AT = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
#: Largest id Postgres BIGSERIAL can hand a delivery.
MAX_DELIVERY_ID = 2**63 - 1


def build_message(delivery_id: int, title: str, lang: str) -> OutgoingMessage:
    """Exactly what `DispatchingService` puts on the wire."""
    reminder = Reminder(title=title, status=ReminderStatus.ACTIVE, snooze_minutes=10)
    category = Category(code="water", title="Вода", emoji="💧")
    return OutgoingMessage(
        chat_id=MAX_DELIVERY_ID,
        text=render_reminder_message(
            reminder, category, FIRE_AT, ZoneInfo("Australia/Lord_Howe"), lang
        ),
        keyboard=reminder_actions_kb(delivery_id, reminder.snooze_minutes, lang),
    )


@pytest.mark.parametrize("lang", ["ru", "en"])
def test_the_reminder_message_satisfies_the_outgoing_contract(lang):
    """The longest reminder a user can create still fits every Telegram limit."""
    message = build_message(MAX_DELIVERY_ID, "я" * REMINDER_TITLE_MAX_LENGTH, lang)

    validate_outgoing(message)


@pytest.mark.parametrize("lang", ["ru", "en"])
def test_every_button_answers_for_this_delivery(lang):
    message = build_message(MAX_DELIVERY_ID, "Пить воду", lang)

    buttons = [button for row in message.keyboard.inline_keyboard for button in row]
    unpacked = [ReactCb.unpack(button.callback_data) for button in buttons]

    assert {callback.action for callback in unpacked} == {"done", "snooze", "skip"}
    assert {callback.delivery_id for callback in unpacked} == {MAX_DELIVERY_ID}


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (TelegramRetryAfter(method=None, message="flood", retry_after=5), ErrorClass.RETRY_AFTER),
        (TelegramForbiddenError(method=None, message="blocked"), ErrorClass.FORBIDDEN),
        (TelegramBadRequest(method=None, message="bad payload"), ErrorClass.BAD_REQUEST),
        (TelegramNotFound(method=None, message="chat not found"), ErrorClass.BAD_REQUEST),
        (TelegramServerError(method=None, message="bad gateway"), ErrorClass.TRANSIENT),
        (TelegramNetworkError(method=None, message="connection reset"), ErrorClass.TRANSIENT),
        (TimeoutError(), ErrorClass.TRANSIENT),
    ],
    ids=lambda value: type(value).__name__ if isinstance(value, BaseException) else value.value,
)
def test_transport_failures_map_onto_the_retry_vocabulary(error, expected):
    assert classify_error(error) is expected


def test_an_unknown_failure_is_retried_rather_than_dropped():
    """Losing a reminder is worse than sending it late; the budget bounds it."""
    assert classify_error(RuntimeError("who knows")) is ErrorClass.TRANSIENT


def test_flood_control_carries_the_delay_telegram_asked_for():
    assert retry_after_seconds(TelegramRetryAfter(method=None, message="flood", retry_after=5)) == 5
    assert retry_after_seconds(TimeoutError()) is None
