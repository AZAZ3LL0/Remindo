"""done / snooze / skip (tech.md 7.4). Every reaction is idempotent."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import Clock
from app.core.logging import get_logger
from app.db.models import Delivery, Occurrence
from app.db.repositories.deliveries import DeliveriesRepository
from app.db.repositories.occurrences import OccurrencesRepository
from app.db.repositories.reminders import RemindersRepository
from app.domain.contracts import (
    TERMINAL_DELIVERY_STATUSES,
    ActionKind,
    DeliveryStatus,
    OccurrenceStatus,
)
from app.domain.errors import NotFoundError, PermissionDeniedError

Action = Literal["done", "snooze", "skip"]

_ACTION_KINDS: dict[Action, ActionKind] = {
    "done": ActionKind.DONE,
    "snooze": ActionKind.SNOOZE,
    "skip": ActionKind.SKIP,
}

_log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class ReactionResult:
    applied: bool
    action: Action
    status: DeliveryStatus
    snoozed_until: datetime | None = None
    reason: str | None = None


class ReactionsService:
    def __init__(self, session: AsyncSession, clock: Clock) -> None:
        self._session = session
        self._clock = clock
        self._deliveries = DeliveriesRepository(session)
        self._occurrences = OccurrencesRepository(session)
        self._reminders = RemindersRepository(session)

    async def react(self, delivery_id: int, user_id: int, action: Action) -> ReactionResult:
        now = self._clock.now()
        delivery = await self._deliveries.get_for_update(delivery_id)
        if delivery is None:
            raise NotFoundError(f"delivery {delivery_id} not found")
        if delivery.user_id != user_id:
            raise PermissionDeniedError("delivery belongs to another recipient")

        occurrence = await self._occurrences.get_by_id(delivery.occurrence_id)
        if occurrence is None:
            raise NotFoundError(f"occurrence {delivery.occurrence_id} not found")

        rejection = self._rejection_reason(delivery, occurrence, now)
        if rejection is not None:
            # A second tap on the same button must not write a second action.
            # Nothing was written; the commit only releases the row lock.
            await self._session.commit()
            return ReactionResult(
                applied=False, action=action, status=delivery.status, reason=rejection
            )

        if action == "snooze":
            result = await self._snooze(delivery, occurrence, now)
        else:
            result = await self._finish(delivery, occurrence, action, now)

        await self._session.commit()
        _log.info(
            "reaction.applied",
            delivery_id=delivery_id,
            user_id=user_id,
            action=action,
            status=result.status.value,
        )
        return result

    def _rejection_reason(
        self, delivery: Delivery, occurrence: Occurrence, now: datetime
    ) -> str | None:
        if delivery.status in TERMINAL_DELIVERY_STATUSES:
            return "already_handled"
        if occurrence.status is OccurrenceStatus.EXPIRED or occurrence.expires_at <= now:
            return "expired"
        if (
            delivery.status is DeliveryStatus.SNOOZED
            and delivery.snoozed_until is not None
            and delivery.snoozed_until > now
        ):
            # Already postponed and not re-delivered yet: the button is stale.
            return "already_handled"
        return None

    async def _snooze(
        self, delivery: Delivery, occurrence: Occurrence, now: datetime
    ) -> ReactionResult:
        reminder = await self._reminders.get_by_id(occurrence.reminder_id)
        minutes = reminder.snooze_minutes if reminder else 10
        snoozed_until = now + timedelta(minutes=minutes)
        await self._deliveries.update_fields(
            delivery.id,
            status=DeliveryStatus.SNOOZED,
            snoozed_until=snoozed_until,
            next_attempt_at=snoozed_until,
            locked_until=None,
        )
        await self._deliveries.add_action(
            delivery.id,
            delivery.user_id,
            ActionKind.SNOOZE,
            created_at=now,
            payload={"minutes": minutes},
        )
        return ReactionResult(
            applied=True,
            action="snooze",
            status=DeliveryStatus.SNOOZED,
            snoozed_until=snoozed_until,
        )

    async def _finish(
        self, delivery: Delivery, occurrence: Occurrence, action: Action, now: datetime
    ) -> ReactionResult:
        status = DeliveryStatus.DONE if action == "done" else DeliveryStatus.SKIPPED
        await self._deliveries.update_fields(
            delivery.id, status=status, reacted_at=now, locked_until=None
        )
        await self._deliveries.add_action(
            delivery.id, delivery.user_id, _ACTION_KINDS[action], created_at=now
        )

        if await self._occurrences.all_deliveries_terminal(occurrence.id):
            await self._occurrences.set_status(
                occurrence.id,
                OccurrenceStatus.DONE if action == "done" else OccurrenceStatus.SKIPPED,
            )
        return ReactionResult(applied=True, action=action, status=status)
