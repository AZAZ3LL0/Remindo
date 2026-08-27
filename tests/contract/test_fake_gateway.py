"""FakeBotGateway is the outgoing contract seam."""

import pytest
from aiogram.exceptions import TelegramRetryAfter
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.callbacks import NOOP_CALLBACK, ReactCb
from app.bot.keyboards.actions import reminder_actions_kb
from app.domain.errors import ContractViolation
from app.gateways.bot_gateway import MessageRef, OutgoingMessage
from app.gateways.fakes import MAX_TEXT_LENGTH, FakeBotGateway


def message(**overrides) -> OutgoingMessage:
    defaults = {
        "chat_id": 42,
        "text": "💧 Пить воду",
        "keyboard": reminder_actions_kb(delivery_id=1, snooze_minutes=10),
    }
    return OutgoingMessage(**{**defaults, **overrides})


async def test_valid_message_is_recorded():
    gateway = FakeBotGateway()
    ref = await gateway.send(message())
    assert gateway.sent == [message()]
    assert ref.chat_id == 42


async def test_zero_chat_id_breaks_the_contract():
    gateway = FakeBotGateway()
    with pytest.raises(ContractViolation, match="chat_id"):
        await gateway.send(message(chat_id=0))


async def test_empty_text_breaks_the_contract():
    gateway = FakeBotGateway()
    with pytest.raises(ContractViolation, match="empty"):
        await gateway.send(message(text=""))


async def test_overlong_text_breaks_the_contract():
    gateway = FakeBotGateway()
    with pytest.raises(ContractViolation, match="exceeds"):
        await gateway.send(message(text="x" * (MAX_TEXT_LENGTH + 1)))


async def test_unknown_callback_data_breaks_the_contract():
    builder = InlineKeyboardBuilder()
    builder.button(text="?", callback_data="not-a-known-factory")
    gateway = FakeBotGateway()
    with pytest.raises(ContractViolation, match="no known factory"):
        await gateway.send(message(keyboard=builder.as_markup()))


async def test_oversized_callback_data_breaks_the_contract():
    builder = InlineKeyboardBuilder()
    builder.button(text="?", callback_data="w:" + "x" * 100)
    gateway = FakeBotGateway()
    with pytest.raises(ContractViolation, match="exceeds 64 bytes"):
        await gateway.send(message(keyboard=builder.as_markup()))


async def test_noop_buttons_are_allowed():
    builder = InlineKeyboardBuilder()
    builder.button(text="1/3", callback_data=NOOP_CALLBACK)
    gateway = FakeBotGateway()
    await gateway.send(message(keyboard=builder.as_markup()))
    assert len(gateway.sent) == 1


async def test_reaction_keyboard_unpacks_into_the_documented_actions():
    gateway = FakeBotGateway()
    await gateway.send(message(keyboard=reminder_actions_kb(7, 15)))
    buttons = [button for row in gateway.sent[0].keyboard.inline_keyboard for button in row]
    actions = [ReactCb.unpack(button.callback_data) for button in buttons]
    assert [action.action for action in actions] == ["done", "snooze", "skip"]
    assert {action.delivery_id for action in actions} == {7}
    assert "15" in buttons[1].text


async def test_programmed_failure_is_raised_once():
    gateway = FakeBotGateway()
    gateway.fail_next(TelegramRetryAfter(method=None, message="flood", retry_after=5))

    with pytest.raises(TelegramRetryAfter):
        await gateway.send(message())
    await gateway.send(message())
    assert len(gateway.sent) == 1


async def test_edits_are_validated_too():
    gateway = FakeBotGateway()
    with pytest.raises(ContractViolation):
        await gateway.edit(MessageRef(chat_id=0, message_id=1), "text", None)
