"""User creation and personal settings."""

from datetime import time

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import Clock
from app.db.models import User
from app.db.repositories.users import UsersRepository
from app.domain.errors import NotFoundError
from app.domain.onboarding import (
    normalize_language,
    normalize_quiet_hours,
    normalize_timezone,
)


class OnboardingService:
    def __init__(
        self,
        session: AsyncSession,
        clock: Clock,
        default_timezone: str,
        default_language: str,
    ) -> None:
        self._session = session
        self._clock = clock
        self._users = UsersRepository(session)
        self._default_timezone = default_timezone
        self._default_language = default_language

    async def ensure_user(
        self,
        tg_user_id: int,
        tg_chat_id: int,
        first_name: str = "",
        username: str | None = None,
    ) -> User:
        """Create the user on first contact, refresh the chat id afterwards."""
        user = await self._users.get_by_tg_id(tg_user_id)
        if user is None:
            user = await self._users.add(
                User(
                    tg_user_id=tg_user_id,
                    tg_chat_id=tg_chat_id,
                    first_name=first_name,
                    username=username,
                    language=self._default_language,
                    timezone=self._default_timezone,
                )
            )
        else:
            user.tg_chat_id = tg_chat_id
            user.first_name = first_name or user.first_name
            user.username = username
            if user.is_blocked:
                user.is_blocked = False
        await self._session.commit()
        return user

    async def set_timezone(self, user_id: int, timezone: str) -> User:
        """Store the zone and, on first contact, close onboarding.

        `onboarded_at` is stamped once: changing the zone later from settings
        must not look like a fresh onboarding in the statistics.
        """
        name = normalize_timezone(timezone)
        user = await self._require_user(user_id)
        user.timezone = name
        if user.onboarded_at is None:
            user.onboarded_at = self._clock.now()
        await self._session.commit()
        return user

    async def set_language(self, user_id: int, language: str) -> User:
        code = normalize_language(language)
        user = await self._require_user(user_id)
        user.language = code.value
        await self._session.commit()
        return user

    async def set_quiet_hours(
        self, user_id: int, quiet_start: time | None, quiet_end: time | None
    ) -> User:
        interval = normalize_quiet_hours(quiet_start, quiet_end)
        user = await self._require_user(user_id)
        user.quiet_start, user.quiet_end = interval if interval else (None, None)
        await self._session.commit()
        return user

    async def _require_user(self, user_id: int) -> User:
        user = await self._users.get_by_id(user_id)
        if user is None:
            raise NotFoundError(f"user {user_id} not found")
        return user
