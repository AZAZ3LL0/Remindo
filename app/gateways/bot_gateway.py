"""Everything external sits behind this protocol."""

import asyncio
from dataclasses import dataclass
from typing import Protocol

from aiogram import Bot
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramRetryAfter,
)
from aiogram.types import InlineKeyboardMarkup

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


class BotGateway(Protocol):
    async def send(self, message: OutgoingMessage) -> MessageRef: ...

    async def edit(
        self, ref: MessageRef, text: str, keyboard: InlineKeyboardMarkup | None
    ) -> None: ...


def classify_error(error: BaseException) -> ErrorClass:
    """Map a transport failure onto the retry policy's vocabulary."""
    if isinstance(error, TelegramRetryAfter):
        return ErrorClass.RETRY_AFTER
    if isinstance(error, TelegramForbiddenError):
        return ErrorClass.FORBIDDEN
    if isinstance(error, TelegramBadRequest):
        return ErrorClass.BAD_REQUEST
    if isinstance(error, TelegramNetworkError | asyncio.TimeoutError | TimeoutError):
        return ErrorClass.TRANSIENT
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
