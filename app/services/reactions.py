"""done / snooze / skip (tech.md 7.4). Every reaction is idempotent."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import Clock
from app.core.logging import get_logger
from app.db.models import Delivery, Occurrence
from app.db.repositories.deliveries import DeliveriesRepository
from app.db.repositories.occurrences import OccurrencesRepository
from app.db.repositories.reminders import RemindersRepository
from app.domain.contracts import ActionKind, DeliveryStatus
from app.domain.errors import NotFoundError, PermissionDeniedError
from app.domain.reactions import (
    Reaction,
    RejectReason,
    check_reactable,
    decide_reaction,
    roll_up_occurrence,
)

Action = Literal["done", "snooze", "skip"]

ACTION_KINDS: dict[Action, ActionKind] = {
    "done": ActionKind.DONE,
    "snooze": ActionKind.SNOOZE,
    "skip": ActionKind.SKIP,
}

_log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class ReactionResult:
    """Outcome of one tap, as the screen needs to report it.

    `reason` is set exactly when nothing was applied: it names the answer the
    user gets instead of a state change.
    """

    applied: bool
    kind: ActionKind
    status: DeliveryStatus
    snoozed_until: datetime | None = None
    reason: RejectReason | None = None


class ReactionsService:
    def __init__(self, session: AsyncSession, clock: Clock) -> None:
        self._session = session
        self._clock = clock
        self._deliveries = DeliveriesRepository(session)
        self._occurrences = OccurrencesRepository(session)
        self._reminders = RemindersRepository(session)

    async def react(self, delivery_id: int, user_id: int, action: Action) -> ReactionResult:
        """Apply one tap under a row lock, so a double tap serialises."""
        now = self._clock.now()
        kind = ACTION_KINDS[action]
        delivery = await self._deliveries.get_for_update(delivery_id)
        if delivery is None:
            raise NotFoundError(f"delivery {delivery_id} not found")
        if delivery.user_id != user_id:
            raise PermissionDeniedError("delivery belongs to another recipient")

        occurrence = await self._occurrences.get_by_id(delivery.occurrence_id)
        if occurrence is None:
            raise NotFoundError(f"occurrence {delivery.occurrence_id} not found")

        reason = check_reactable(
            kind,
            delivery_status=delivery.status,
            occurrence_status=occurrence.status,
            expires_at=occurrence.expires_at,
            snoozed_until=delivery.snoozed_until,
            now=now,
        )
        if reason is not None:
            # Nothing was written; the commit only releases the row lock.
            await self._session.commit()
            _log.info(
                "reaction.rejected",
                delivery_id=delivery_id,
                user_id=user_id,
                action=action,
                reason=reason.value,
            )
            return ReactionResult(applied=False, kind=kind, status=delivery.status, reason=reason)

        snooze_minutes = await self._snooze_minutes(occurrence)
        reaction = decide_reaction(kind, now, snooze_minutes)
        await self._write(delivery, reaction, now, snooze_minutes)
        await self._close_occurrence(occurrence, reaction)
        await self._session.commit()

        _log.info(
            "reaction.applied",
            delivery_id=delivery_id,
            user_id=user_id,
            action=action,
            status=reaction.status.value,
        )
        return ReactionResult(
            applied=True,
            kind=reaction.kind,
            status=reaction.status,
            snoozed_until=reaction.snoozed_until,
        )

    async def _snooze_minutes(self, occurrence: Occurrence) -> int:
        reminder = await self._reminders.get_by_id(occurrence.reminder_id)
        if reminder is None:
            raise NotFoundError(f"reminder {occurrence.reminder_id} not found")
        return reminder.snooze_minutes

    async def _write(
        self, delivery: Delivery, reaction: Reaction, now: datetime, snooze_minutes: int
    ) -> None:
        values: dict[str, object] = {
            "status": reaction.status,
            # The lease is dropped with the reaction: the row either left the
            # queue or carries a new due moment, and either way no worker owns it.
            "locked_until": None,
        }
        if reaction.reacted_at is not None:
            values["reacted_at"] = reaction.reacted_at
        if reaction.snoozed_until is not None:
            values["snoozed_until"] = reaction.snoozed_until
            values["next_attempt_at"] = reaction.snoozed_until

        await self._deliveries.update_fields(delivery.id, **values)
        await self._deliveries.add_action(
            delivery.id,
            delivery.user_id,
            reaction.kind,
            created_at=now,
            payload={"minutes": snooze_minutes} if reaction.kind is ActionKind.SNOOZE else None,
        )

    async def _close_occurrence(self, occurrence: Occurrence, reaction: Reaction) -> None:
        """Roll the occurrence up once its last recipient has answered."""
        if not reaction.is_terminal:
            return
        status = roll_up_occurrence(
            reaction.kind,
            every_delivery_terminal=await self._occurrences.all_deliveries_terminal(occurrence.id),
        )
        if status is not None:
            await self._occurrences.set_status(occurrence.id, status)
