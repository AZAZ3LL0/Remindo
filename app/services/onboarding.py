"""User creation and personal settings."""

from datetime import time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import Clock
from app.db.models import User
from app.db.repositories.users import UsersRepository
from app.domain.errors import NotFoundError, ValidationError


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
        try:
            ZoneInfo(timezone)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValidationError(f"unknown timezone: {timezone}") from exc

        user = await self._require_user(user_id)
        user.timezone = timezone
        if user.onboarded_at is None:
            user.onboarded_at = self._clock.now()
        await self._session.commit()
        return user

    async def set_language(self, user_id: int, language: str) -> User:
        if language not in ("ru", "en"):
            raise ValidationError(f"unsupported language: {language}")
        user = await self._require_user(user_id)
        user.language = language
        await self._session.commit()
        return user

    async def set_quiet_hours(
        self, user_id: int, quiet_start: time | None, quiet_end: time | None
    ) -> User:
        if (quiet_start is None) != (quiet_end is None):
            raise ValidationError("quiet hours must be set or cleared together")
        user = await self._require_user(user_id)
        user.quiet_start = quiet_start
        user.quiet_end = quiet_end
        await self._session.commit()
        return user

    async def _require_user(self, user_id: int) -> User:
        user = await self._users.get_by_id(user_id)
        if user is None:
            raise NotFoundError(f"user {user_id} not found")
        return user
