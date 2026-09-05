"""Everything external sits behind this protocol."""

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from aiogram import Bot
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramNotFound,
    TelegramRetryAfter,
    TelegramServerError,
)
from aiogram.types import BotCommand, InlineKeyboardMarkup

from app.domain.contracts import ErrorClass


@dataclass(frozen=True)
class OutgoingMessage:
    chat_id: int
    text: str
    keyboard: InlineKeyboardMarkup | None
    parse_mode: str = "HTML"


@dataclass(frozen=True)
class MessageRef:
    chat_id: int
    message_id: int


@dataclass(frozen=True, slots=True)
class BotCommandSpec:
    """One entry of the Telegram command menu (tech.md 25.2).

    `command` carries no leading slash, the way Telegram accepts it. The slash
    is drawn by the help renderer: storing it here would keep one value in two
    shapes.
    """

    command: str
    description: str


class BotGateway(Protocol):
    async def send(self, message: OutgoingMessage) -> MessageRef: ...

    async def edit(
        self, ref: MessageRef, text: str, keyboard: InlineKeyboardMarkup | None
    ) -> None: ...

    async def set_commands(self, commands: Sequence[BotCommandSpec], lang: str) -> None: ...


def classify_error(error: BaseException) -> ErrorClass:
    """Map a transport failure onto the retry policy's vocabulary."""
    if isinstance(error, TelegramRetryAfter):
        return ErrorClass.RETRY_AFTER
    if isinstance(error, TelegramForbiddenError):
        return ErrorClass.FORBIDDEN
    if isinstance(error, TelegramBadRequest | TelegramNotFound):
        # A missing chat is as permanent as a malformed payload: the recipient
        # deleted the account, and five more attempts change nothing.
        return ErrorClass.BAD_REQUEST
    if isinstance(
        error, TelegramServerError | TelegramNetworkError | asyncio.TimeoutError | TimeoutError
    ):
        return ErrorClass.TRANSIENT
    # An unknown failure is retried rather than dropped: the attempt budget
    # bounds it, and losing a reminder is worse than sending it late.
    return ErrorClass.TRANSIENT


def retry_after_seconds(error: BaseException) -> int | None:
    return int(error.retry_after) if isinstance(error, TelegramRetryAfter) else None


class AiogramBotGateway:
    """Real Telegram transport."""

    def __init__(self, bot: Bot) -> None:
        self._bot = bot

    async def send(self, message: OutgoingMessage) -> MessageRef:
        sent = await self._bot.send_message(
            chat_id=message.chat_id,
            text=message.text,
            reply_markup=message.keyboard,
            parse_mode=message.parse_mode,
        )
        return MessageRef(chat_id=message.chat_id, message_id=sent.message_id)

    async def edit(self, ref: MessageRef, text: str, keyboard: InlineKeyboardMarkup | None) -> None:
        await self._bot.edit_message_text(
            chat_id=ref.chat_id,
            message_id=ref.message_id,
            text=text,
            reply_markup=keyboard,
        )

    async def set_commands(self, commands: Sequence[BotCommandSpec], lang: str) -> None:
        await self._bot.set_my_commands(
            [BotCommand(command=spec.command, description=spec.description) for spec in commands],
            language_code=lang,
        )
