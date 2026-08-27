"""dispatcher.deliver: claim, send, apply the retry policy (tech.md 7.2)."""

from dataclasses import dataclass
from datetime import timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.actions import reminder_actions_kb
from app.bot.render.reminder import render_reminder_message
from app.core.clock import Clock
from app.core.logging import get_logger
from app.db.models import Category, Delivery, Occurrence, Reminder, User
from app.db.repositories.categories import CategoriesRepository
from app.db.repositories.deliveries import DeliveriesRepository
from app.db.repositories.occurrences import OccurrencesRepository
from app.db.repositories.reminders import RemindersRepository
from app.db.repositories.users import UsersRepository
from app.domain.contracts import DeliveryStatus, ErrorClass, OccurrenceStatus
from app.domain.retry import next_attempt, should_retry
from app.gateways.bot_gateway import (
    BotGateway,
    OutgoingMessage,
    classify_error,
    retry_after_seconds,
)

_log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class DispatchResult:
    claimed: int = 0
    sent: int = 0
    retried: int = 0
    failed: int = 0
    blocked: int = 0


class DispatchingService:
    def __init__(
        self,
        session: AsyncSession,
        clock: Clock,
        gateway: BotGateway,
        batch_size: int,
        lock_seconds: int,
    ) -> None:
        self._session = session
        self._clock = clock
        self._gateway = gateway
        self._batch_size = batch_size
        self._lock = timedelta(seconds=lock_seconds)
        self._deliveries = DeliveriesRepository(session)
        self._occurrences = OccurrencesRepository(session)
        self._reminders = RemindersRepository(session)
        self._categories = CategoriesRepository(session)
        self._users = UsersRepository(session)

    async def deliver(self) -> DispatchResult:
        """One dispatcher cycle. Delivery is at-least-once by design."""
        now = self._clock.now()
        claimed = await self._deliveries.claim_due(now, self._lock, self._batch_size)
        # The lease is committed before any network call, so a crash mid-send
        # cannot hand the same row to another worker before it expires.
        await self._session.commit()

        sent = retried = failed = blocked = 0
        for delivery in claimed:
            outcome = await self._deliver_one(delivery)
            sent += outcome == "sent"
            retried += outcome == "retried"
            failed += outcome == "failed"
            blocked += outcome == "blocked"

        result = DispatchResult(
            claimed=len(claimed), sent=sent, retried=retried, failed=failed, blocked=blocked
        )
        _log.info("dispatcher.deliver", **result.__dict__)
        return result

    async def _deliver_one(self, delivery: Delivery) -> str:
        context = await self._load_context(delivery)
        if context is None:
            await self._deliveries.update_fields(
                delivery.id,
                status=DeliveryStatus.FAILED,
                error_code="context_missing",
                locked_until=None,
            )
            await self._session.commit()
            return "failed"

        occurrence, reminder, category, user = context
        message = OutgoingMessage(
            chat_id=user.tg_chat_id,
            text=render_reminder_message(
                reminder, category, occurrence.fire_at, ZoneInfo(user.timezone), user.language
            ),
            keyboard=reminder_actions_kb(delivery.id, reminder.snooze_minutes, user.language),
        )

        try:
            ref = await self._gateway.send(message)
        except Exception as error:
            return await self._handle_failure(delivery, error)

        now = self._clock.now()
        await self._deliveries.update_fields(
            delivery.id,
            status=DeliveryStatus.SENT,
            sent_at=now,
            tg_message_id=ref.message_id,
            locked_until=None,
            error_code=None,
        )
        if occurrence.status in (OccurrenceStatus.PENDING, OccurrenceStatus.DISPATCHING):
            await self._occurrences.set_status(occurrence.id, OccurrenceStatus.SENT)
        await self._session.commit()
        return "sent"

    async def _handle_failure(self, delivery: Delivery, error: BaseException) -> str:
        error_class = classify_error(error)
        now = self._clock.now()

        if error_class is ErrorClass.FORBIDDEN:
            await self._deliveries.update_fields(
                delivery.id,
                status=DeliveryStatus.BLOCKED,
                error_code=type(error).__name__,
                locked_until=None,
            )
            await self._users.mark_blocked(delivery.user_id, True)
            await self._session.commit()
            _log.warning("dispatcher.blocked", delivery_id=delivery.id, user_id=delivery.user_id)
            return "blocked"

        if not should_retry(delivery.attempts, error_class):
            await self._deliveries.update_fields(
                delivery.id,
                status=DeliveryStatus.FAILED,
                error_code=type(error).__name__,
                locked_until=None,
            )
            await self._session.commit()
            _log.error(
                "dispatcher.failed",
                delivery_id=delivery.id,
                error_class=error_class.value,
                attempts=delivery.attempts,
            )
            return "failed"

        await self._deliveries.update_fields(
            delivery.id,
            status=DeliveryStatus.PENDING,
            next_attempt_at=next_attempt(
                delivery.attempts, error_class, now, retry_after=retry_after_seconds(error)
            ),
            error_code=type(error).__name__,
            locked_until=None,
        )
        await self._session.commit()
        return "retried"

    async def _load_context(
        self, delivery: Delivery
    ) -> tuple[Occurrence, Reminder, Category, User] | None:
        occurrence = await self._occurrences.get_by_id(delivery.occurrence_id)
        if occurrence is None:
            return None
        reminder = await self._reminders.get_by_id(occurrence.reminder_id)
        if reminder is None:
            return None
        category = await self._categories.get_by_id(reminder.category_id)
        user = await self._users.get_by_id(delivery.user_id)
        if category is None or user is None:
            return None
        return occurrence, reminder, category, user
