"""Shared reminders: invite, accept, unsubscribe (tech.md 22).

The only place that opens a transaction for the sharing screens, and the only
place that draws the entropy an invitation token is made of: the domain stays
pure and gets the bytes handed to it (tech.md 22.2).
"""

import secrets
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import Clock
from app.core.logging import get_logger
from app.db.models import Reminder, ReminderInvite, ReminderRecipient, User
from app.db.repositories.deliveries import DeliveriesRepository
from app.db.repositories.invites import InvitesRepository
from app.db.repositories.occurrences import OccurrencesRepository
from app.db.repositories.reminders import RecipientsRepository, RemindersRepository
from app.db.repositories.users import UsersRepository
from app.domain.contracts import (
    INVITE_TOKEN_BYTES,
    INVITE_TTL_HOURS,
    REMINDER_WATCHERS_MAX,
    RecipientRole,
)
from app.domain.errors import (
    InviteExpiredError,
    NotFoundError,
    PermissionDeniedError,
)
from app.domain.sharing import InviteState, check_join, invite_state, new_invite_token

_log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class Participant:
    """One recipient of a reminder, flattened for the renderer."""

    user: User
    role: RecipientRole
    accepted: bool


@dataclass(frozen=True, slots=True)
class SharedReminder:
    """A reminder somebody else shares with the user, and how they hold it."""

    reminder: Reminder
    owner: User | None
    accepted: bool


class SharingService:
    def __init__(self, session: AsyncSession, clock: Clock) -> None:
        self._session = session
        self._clock = clock
        self._reminders = RemindersRepository(session)
        self._recipients = RecipientsRepository(session)
        self._invites = InvitesRepository(session)
        self._occurrences = OccurrencesRepository(session)
        self._deliveries = DeliveriesRepository(session)
        self._users = UsersRepository(session)

    async def live_invite(self, owner_id: int, reminder_id: int) -> ReminderInvite | None:
        """The invitation of this reminder that still lets somebody in."""
        await self._owned(owner_id, reminder_id)
        invite = await self._invites.get_live(reminder_id)
        if invite is None:
            return None
        state = invite_state(invite.expires_at, invite.revoked_at, self._clock.now())
        return invite if state is InviteState.LIVE else None

    async def issue_invite(self, owner_id: int, reminder_id: int) -> ReminderInvite:
        """Mint a link, taking the previous one back (tech.md 22.1).

        One live invitation per reminder is a partial unique index, so minting
        has to revoke first: with two live links, revoking one would revoke
        nothing.
        """
        await self._owned(owner_id, reminder_id)
        now = self._clock.now()
        await self._invites.revoke_live(reminder_id, now)
        invite = await self._invites.add(
            ReminderInvite(
                reminder_id=reminder_id,
                token=new_invite_token(secrets.token_bytes(INVITE_TOKEN_BYTES)),
                created_by=owner_id,
                expires_at=now + timedelta(hours=INVITE_TTL_HOURS),
            )
        )
        await self._session.commit()
        _log.info("sharing.invite_issued", reminder_id=reminder_id, user_id=owner_id)
        return invite

    async def revoke_invite(self, owner_id: int, reminder_id: int) -> bool:
        """Take the live link back. Idempotent: a second press revokes nothing."""
        await self._owned(owner_id, reminder_id)
        revoked = await self._invites.revoke_live(reminder_id, self._clock.now())
        await self._session.commit()
        return revoked > 0

    async def open_invite(self, token: str, user: User) -> tuple[Reminder, User]:
        """Resolve a deep link into the reminder it invites to (tech.md 22.5).

        A pending recipient row is left behind, so the invitation survives the
        onboarding the invitee usually has to go through first, and the answer
        can arrive from a button that carries only the reminder id.
        """
        invite = await self._invites.get_by_token(token)
        if invite is None:
            raise NotFoundError("no such invitation")
        if invite_state(invite.expires_at, invite.revoked_at, self._clock.now()) is not (
            InviteState.LIVE
        ):
            raise InviteExpiredError("invitation is revoked or expired")

        # Locked, so counting the watchers and adding one is a single decision:
        # two people following the same link at the limit would otherwise both
        # find room (tech.md 22.4).
        reminder = await self._reminders.get_for_update(invite.reminder_id)
        if reminder is None:
            raise NotFoundError("the reminder is gone")

        existing = await self._recipients.get(reminder.id, user.id)
        check_join(
            None if existing is None else existing.role,
            await self._recipients.count_watchers(reminder.id),
            REMINDER_WATCHERS_MAX,
        )
        if existing is None:
            await self._recipients.add(
                ReminderRecipient(
                    reminder_id=reminder.id,
                    user_id=user.id,
                    role=RecipientRole.WATCHER,
                    accepted_at=None,
                )
            )
        # Committed even when nothing was added: the lock lives until the
        # transaction ends, and holding it past the decision serialises nothing.
        await self._session.commit()

        return reminder, await self._owner_of(reminder)

    async def pending_invite(self, user_id: int) -> Reminder | None:
        """The invitation waiting for an answer, if the user has one.

        Onboarding calls it: an invitee usually meets the bot through the link,
        and the timezone question has to come first (tech.md 22.5).
        """
        shared = await self._recipients.list_shared_with(user_id, limit=1, offset=0)
        for recipient, reminder in shared:
            if recipient.accepted_at is None:
                return reminder
        return None

    async def accept(self, user_id: int, reminder_id: int) -> Reminder:
        """Start receiving the reminder, and catch up on what is queued.

        Idempotent: accepting twice moves nothing and backfills nothing, since
        the update only touches a row still pending and the delivery insert is
        held by the (occurrence_id, user_id) key.
        """
        reminder, _ = await self._participation(user_id, reminder_id)
        now = self._clock.now()
        accepted = await self._recipients.accept(reminder_id, user_id, now)
        backfilled = 0
        if accepted:
            backfilled = await self._backfill_deliveries(reminder_id, user_id, now)
        await self._session.commit()
        _log.info(
            "sharing.accepted",
            reminder_id=reminder_id,
            user_id=user_id,
            deliveries_created=backfilled,
        )
        return reminder

    async def decline(self, user_id: int, reminder_id: int) -> None:
        """Refuse a pending invitation. It has no deliveries to take back."""
        await self._recipients.remove_watcher(reminder_id, user_id)
        await self._session.commit()

    async def leave(self, user_id: int, reminder_id: int) -> None:
        """Stop receiving a shared reminder (tech.md 22.6).

        Idempotent: called twice, the second call drops nothing and changes
        nothing else.
        """
        await self._deliveries.delete_pending_for_recipient(reminder_id, user_id)
        await self._recipients.remove_watcher(reminder_id, user_id)
        await self._session.commit()
        _log.info("sharing.left", reminder_id=reminder_id, user_id=user_id)

    async def get_watched(self, user_id: int, reminder_id: int) -> tuple[Reminder, User, bool]:
        """The reminder as a watcher sees it: read only, plus who shares it."""
        reminder, recipient = await self._participation(user_id, reminder_id)
        return reminder, await self._owner_of(reminder), recipient.accepted_at is not None

    async def list_shared_with(
        self, user_id: int, page: int, page_size: int
    ) -> tuple[Sequence[SharedReminder], int]:
        rows = await self._recipients.list_shared_with(
            user_id, limit=page_size, offset=page * page_size
        )
        owners = {
            owner.id: owner
            for owner in await self._users.list_by_ids([row[1].owner_id for row in rows])
        }
        items = [
            SharedReminder(
                reminder=reminder,
                owner=owners.get(reminder.owner_id),
                accepted=recipient.accepted_at is not None,
            )
            for recipient, reminder in rows
        ]
        return items, await self._recipients.count_shared_with(user_id)

    async def list_participants(self, owner_id: int, reminder_id: int) -> Sequence[Participant]:
        """Everyone the reminder is addressed to, the owner included."""
        await self._owned(owner_id, reminder_id)
        rows = await self._recipients.list_for_reminder(reminder_id)
        users = {
            user.id: user for user in await self._users.list_by_ids([row.user_id for row in rows])
        }
        return [
            Participant(user=user, role=row.role, accepted=row.accepted_at is not None)
            for row in rows
            if (user := users.get(row.user_id)) is not None
        ]

    async def count_watchers(self, reminder_id: int) -> int:
        """Recipients other than the owner the reminder actually reaches."""
        return await self._recipients.count_accepted_watchers(reminder_id)

    async def _backfill_deliveries(self, reminder_id: int, user_id: int, now: datetime) -> int:
        """Queue what the planner materialised before this recipient joined."""
        upcoming = await self._occurrences.list_upcoming(reminder_id, now)
        return await self._deliveries.insert_missing(
            [
                {
                    "occurrence_id": occurrence.id,
                    "user_id": user_id,
                    "next_attempt_at": occurrence.fire_at,
                }
                for occurrence in upcoming
            ]
        )

    async def _owned(self, owner_id: int, reminder_id: int) -> Reminder:
        reminder = await self._reminders.get_by_id(reminder_id)
        if reminder is None:
            raise NotFoundError(f"reminder {reminder_id} not found")
        if reminder.owner_id != owner_id:
            raise PermissionDeniedError("reminder belongs to another user")
        return reminder

    async def _participation(
        self, user_id: int, reminder_id: int
    ) -> tuple[Reminder, ReminderRecipient]:
        recipient = await self._recipients.get(reminder_id, user_id)
        if recipient is None or recipient.role is not RecipientRole.WATCHER:
            raise NotFoundError(f"user {user_id} does not watch reminder {reminder_id}")
        reminder = await self._reminders.get_by_id(reminder_id)
        if reminder is None:
            raise NotFoundError(f"reminder {reminder_id} not found")
        return reminder, recipient

    async def _owner_of(self, reminder: Reminder) -> User:
        owner = await self._users.get_by_id(reminder.owner_id)
        if owner is None:
            raise NotFoundError(f"owner {reminder.owner_id} not found")
        return owner
