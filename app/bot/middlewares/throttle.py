"""Per-user rate limit. Keeps a burst of taps from flooding the database."""

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, TelegramObject

from app.core.clock import Clock


class ThrottleMiddleware(BaseMiddleware):
    def __init__(self, clock: Clock, min_interval_seconds: float = 0.3) -> None:
        self._clock = clock
        self._min_interval = min_interval_seconds
        self._last_seen: dict[int, float] = {}

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        tg_user = data.get("event_from_user")
        if tg_user is None:
            return await handler(event, data)

        now = self._clock.now().timestamp()
        previous = self._last_seen.get(tg_user.id)
        if previous is not None and now - previous < self._min_interval:
            if isinstance(event, CallbackQuery):
                await event.answer()
            return None

        self._last_seen[tg_user.id] = now
        return await handler(event, data)
