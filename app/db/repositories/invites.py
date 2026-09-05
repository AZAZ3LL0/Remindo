"""Invitation queries (tech.md 22.1). No transaction control here."""

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ReminderInvite


class InvitesRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_token(self, token: str) -> ReminderInvite | None:
        stmt = sa.select(ReminderInvite).where(ReminderInvite.token == token)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_live(self, reminder_id: int) -> ReminderInvite | None:
        """The one invitation the partial unique index allows to be live.

        Expiry is left to the caller: the row is still the live one in the
        index's sense, and the domain decides what it is worth (tech.md 22.2).
        """
        stmt = sa.select(ReminderInvite).where(
            ReminderInvite.reminder_id == reminder_id,
            ReminderInvite.revoked_at.is_(None),
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def add(self, invite: ReminderInvite) -> ReminderInvite:
        self._session.add(invite)
        await self._session.flush()
        return invite

    async def revoke_live(self, reminder_id: int, now: datetime) -> int:
        """Take back the live invitation, if there is one.

        Returns how many rows it took back, so a second press can tell the user
        there was nothing left to revoke.
        """
        stmt = (
            sa.update(ReminderInvite)
            .where(
                ReminderInvite.reminder_id == reminder_id,
                ReminderInvite.revoked_at.is_(None),
            )
            .values(revoked_at=now)
            .returning(ReminderInvite.id)
        )
        return len((await self._session.execute(stmt)).scalars().all())
