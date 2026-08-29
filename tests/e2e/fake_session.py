"""Offline aiogram session, so updates can travel through real handlers.

The bot process is exercised end to end without a token and without network:
outgoing API calls are recorded and answered with plausible objects.
"""

from collections import deque
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from itertools import count
from typing import Any

from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.methods import (
    AnswerCallbackQuery,
    EditMessageReplyMarkup,
    EditMessageText,
    SendMessage,
    TelegramMethod,
)
from aiogram.types import Chat, Message


class FakeTelegramSession(BaseSession):
    def __init__(self) -> None:
        super().__init__()
        self.requests: list[TelegramMethod[Any]] = []
        self._message_ids = count(1)
        self._failures: deque[tuple[BaseException, type[TelegramMethod[Any]] | None]] = deque()

    def fail_next(self, error: BaseException, on: type[TelegramMethod[Any]] | None = None) -> None:
        """Program an API call to raise, optionally only a call of one method.

        Narrowing by method matters because one handler makes several calls:
        a failure meant for the redraw must not land on the callback answer.
        """
        self._failures.append((error, on))

    @property
    def sent_messages(self) -> list[SendMessage]:
        return [request for request in self.requests if isinstance(request, SendMessage)]

    @property
    def edits(self) -> list[EditMessageText]:
        return [request for request in self.requests if isinstance(request, EditMessageText)]

    @property
    def answers(self) -> list[AnswerCallbackQuery]:
        return [request for request in self.requests if isinstance(request, AnswerCallbackQuery)]

    async def make_request(
        self, bot: Bot, method: TelegramMethod[Any], timeout: int | None = None
    ) -> Any:
        self.requests.append(method)
        if self._failures and isinstance(method, self._failures[0][1] or type(method)):
            raise self._failures.popleft()[0]
        if isinstance(method, SendMessage):
            return self._message(chat_id=method.chat_id, text=method.text)
        if isinstance(method, EditMessageText):
            return self._message(chat_id=method.chat_id or 0, text=method.text)
        if isinstance(method, EditMessageReplyMarkup):
            return self._message(chat_id=method.chat_id or 0, text="")
        return True

    def _message(self, chat_id: int | str, text: str) -> Message:
        return Message(
            message_id=next(self._message_ids),
            date=datetime.now(UTC),
            chat=Chat(id=int(chat_id), type="private"),
            text=text,
        )

    async def stream_content(
        self,
        url: str,
        headers: dict[str, Any] | None = None,
        timeout: int = 30,
        chunk_size: int = 65536,
        raise_for_status: bool = True,
    ) -> AsyncGenerator[bytes, None]:
        yield b""

    async def close(self) -> None:
        return None
