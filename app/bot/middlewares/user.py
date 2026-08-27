"""Resolve the current user and put it into handler data."""

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject
from aiogram.types import User as TgUser

from app.core.clock import Clock
from app.services.onboarding import OnboardingService


class CurrentUserMiddleware(BaseMiddleware):
    def __init__(self, clock: Clock, default_timezone: str, default_language: str) -> None:
        self._clock = clock
        self._default_timezone = default_timezone
        self._default_language = default_language

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        tg_user: TgUser | None = data.get("event_from_user")
        session = data.get("session")
        if tg_user is not None and session is not None and not tg_user.is_bot:
            service = OnboardingService(
                session, self._clock, self._default_timezone, self._default_language
            )
            data["user"] = await service.ensure_user(
                tg_user_id=tg_user.id,
                tg_chat_id=data["event_chat"].id if data.get("event_chat") else tg_user.id,
                first_name=tg_user.first_name or "",
                username=tg_user.username,
            )
        return await handler(event, data)
