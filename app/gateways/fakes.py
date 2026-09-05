"""Fakes used by both the test suite and the dev runtime (USE_FAKE_BOT=true).

`FakeBotGateway` is the contract seam: it fails loudly when a slice sends a
message that Telegram would reject or a keyboard the callback contract does not
recognise.
"""

import re
from collections import deque
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from itertools import count

from aiogram.types import InlineKeyboardMarkup

from app.bot.callbacks import KNOWN_CALLBACK_FACTORIES, NOOP_CALLBACK
from app.core.logging import get_logger
from app.domain.errors import ContractViolation
from app.gateways.bot_gateway import BotCommandSpec, MessageRef, OutgoingMessage

MAX_TEXT_LENGTH = 4096
MAX_CALLBACK_BYTES = 64

#: Telegram's own limits on the command menu (tech.md 25.2), mirrored so the
#: fake refuses a menu the real transport would.
COMMAND_PATTERN = re.compile(r"^[a-z0-9_]{1,32}$")
COMMAND_DESCRIPTION_MAX_LENGTH = 256
COMMANDS_MAX = 100

_log = get_logger(__name__)


class FakeClock:
    """Deterministic clock. Tests move time instead of sleeping."""

    def __init__(self, moment: datetime) -> None:
        self._moment = self._normalize(moment)

    @staticmethod
    def _normalize(moment: datetime) -> datetime:
        if moment.tzinfo is None:
            raise ValueError("clock moment must be timezone-aware")
        return moment.astimezone(UTC)

    def now(self) -> datetime:
        return self._moment

    def advance(self, delta: timedelta) -> datetime:
        self._moment += delta
        return self._moment

    def set(self, moment: datetime) -> datetime:
        self._moment = self._normalize(moment)
        return self._moment


def validate_outgoing(message: OutgoingMessage) -> None:
    """Enforce the outgoing contract. Raises ContractViolation on a breach."""
    if message.chat_id == 0:
        raise ContractViolation("chat_id must not be zero")
    if not message.text:
        raise ContractViolation("message text must not be empty")
    if len(message.text) > MAX_TEXT_LENGTH:
        raise ContractViolation(f"message text exceeds {MAX_TEXT_LENGTH} characters")
    validate_keyboard(message.keyboard)


def validate_keyboard(keyboard: InlineKeyboardMarkup | None) -> None:
    if keyboard is None:
        return
    for row in keyboard.inline_keyboard:
        for button in row:
            data = button.callback_data
            if data is None:
                continue
            if len(data.encode()) > MAX_CALLBACK_BYTES:
                raise ContractViolation(f"callback_data exceeds {MAX_CALLBACK_BYTES} bytes: {data}")
            if data == NOOP_CALLBACK:
                continue
            if not _unpacks(data):
                raise ContractViolation(f"callback_data has no known factory: {data}")


def validate_commands(commands: Sequence[BotCommandSpec]) -> None:
    """Enforce the command menu contract. Raises ContractViolation on a breach.

    Without this the menu would be the one part of the bot that USE_FAKE_BOT
    cannot check, and the first thing to break for a live user.
    """
    if len(commands) > COMMANDS_MAX:
        raise ContractViolation(f"command menu exceeds {COMMANDS_MAX} entries")
    seen: set[str] = set()
    for spec in commands:
        if not COMMAND_PATTERN.match(spec.command):
            raise ContractViolation(f"command is not a valid Telegram command: {spec.command!r}")
        if spec.command in seen:
            raise ContractViolation(f"command listed twice: {spec.command}")
        seen.add(spec.command)
        if not spec.description.strip():
            raise ContractViolation(f"command {spec.command} has no description")
        if len(spec.description) > COMMAND_DESCRIPTION_MAX_LENGTH:
            raise ContractViolation(
                f"description of {spec.command} exceeds {COMMAND_DESCRIPTION_MAX_LENGTH}"
            )


def _unpacks(data: str) -> bool:
    for factory in KNOWN_CALLBACK_FACTORIES:
        try:
            factory.unpack(data)
        except (ValueError, TypeError):
            continue
        return True
    return False


class FakeBotGateway:
    """Records outgoing traffic and validates it against the contract."""

    def __init__(self) -> None:
        self.sent: list[OutgoingMessage] = []
        self.edited: list[tuple[MessageRef, str, InlineKeyboardMarkup | None]] = []
        #: Last menu published per language. Publishing twice leaves one entry,
        #: because Telegram's own call replaces rather than appends.
        self.commands: dict[str, tuple[BotCommandSpec, ...]] = {}
        self._failures: deque[BaseException] = deque()
        self._message_ids = count(1000)

    def fail_next(self, error: BaseException) -> None:
        """Program the next call to raise. Queued calls fail in order."""
        self._failures.append(error)

    def reset(self) -> None:
        self.sent.clear()
        self.edited.clear()
        self.commands.clear()
        self._failures.clear()

    async def send(self, message: OutgoingMessage) -> MessageRef:
        validate_outgoing(message)
        if self._failures:
            raise self._failures.popleft()
        self.sent.append(message)
        _log.debug("fake_bot.send", chat_id=message.chat_id)
        return MessageRef(chat_id=message.chat_id, message_id=next(self._message_ids))

    async def edit(self, ref: MessageRef, text: str, keyboard: InlineKeyboardMarkup | None) -> None:
        validate_outgoing(OutgoingMessage(chat_id=ref.chat_id, text=text, keyboard=keyboard))
        if self._failures:
            raise self._failures.popleft()
        self.edited.append((ref, text, keyboard))

    async def set_commands(self, commands: Sequence[BotCommandSpec], lang: str) -> None:
        validate_commands(commands)
        if self._failures:
            raise self._failures.popleft()
        self.commands[lang] = tuple(commands)
        _log.debug("fake_bot.set_commands", lang=lang, count=len(commands))
