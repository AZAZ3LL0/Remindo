"""dispatcher.deliver: claim, send, apply the retry policy (tech.md 7.2)."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.actions import reminder_actions_kb
from app.bot.render.reminder import render_reminder_message
from app.bot.render.texts import T
from app.core.clock import Clock
from app.core.logging import get_logger
from app.db.models import Category, Delivery, FSMState, Occurrence, Reminder, User
from app.db.repositories.categories import CategoriesRepository
from app.db.repositories.deliveries import DeliveriesRepository
from app.db.repositories.occurrences import OccurrencesRepository
from app.db.repositories.reminders import RemindersRepository
from app.db.repositories.users import UsersRepository
from app.domain.contracts import ActionKind, DeliveryStatus, ErrorClass, OccurrenceStatus
from app.domain.retry import next_attempt, should_retry
from app.gateways.bot_gateway import (
    BotGateway,
    MessageRef,
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


@dataclass(frozen=True, slots=True)
class SweepResult:
    expired: int = 0
    repeated: int = 0
    locks_released: int = 0
    fsm_states_purged: int = 0


class ReaperService:
    """reaper.sweep (tech.md 7.3).

    It lives next to the dispatcher because both own the delivery lifecycle,
    and transactions may only be opened by a service.
    """

    def __init__(
        self,
        session: AsyncSession,
        clock: Clock,
        gateway: BotGateway,
        batch_size: int = 100,
        fsm_ttl_hours: int = 24,
    ) -> None:
        self._session = session
        self._clock = clock
        self._gateway = gateway
        self._batch_size = batch_size
        self._fsm_ttl = timedelta(hours=fsm_ttl_hours)
        self._deliveries = DeliveriesRepository(session)
        self._occurrences = OccurrencesRepository(session)
        self._users = UsersRepository(session)

    async def sweep(self) -> SweepResult:
        now = self._clock.now()
        expired = await self._expire_overdue(now)
        repeated = await self._repeat_unanswered(now)
        locks = await self._deliveries.release_stale_locks(now)
        purged = await self._purge_fsm_states(now)
        await self._session.commit()

        result = SweepResult(
            expired=expired, repeated=repeated, locks_released=locks, fsm_states_purged=purged
        )
        _log.info("reaper.sweep", **result.__dict__)
        return result

    async def _expire_overdue(self, now: datetime) -> int:
        overdue = await self._occurrences.list_expired(now, self._batch_size)
        for occurrence in overdue:
            for delivery in await self._deliveries.list_sent_for_occurrence(occurrence.id):
                await self._deliveries.add_action(
                    delivery.id, delivery.user_id, ActionKind.AUTO_EXPIRE
                )
                await self._strip_keyboard(delivery)
            await self._occurrences.set_status(occurrence.id, OccurrenceStatus.EXPIRED)
        return len(overdue)

    async def _strip_keyboard(self, delivery: Delivery) -> None:
        """Drop the buttons so an expired reminder cannot be answered."""
        if delivery.tg_message_id is None:
            return
        user = await self._users.get_by_id(delivery.user_id)
        if user is None:
            return
        try:
            await self._gateway.edit(
                MessageRef(chat_id=user.tg_chat_id, message_id=delivery.tg_message_id),
                T("react.expired", user.language),
                None,
            )
        except Exception as error:
            _log.warning("reaper.edit_failed", delivery_id=delivery.id, error=type(error).__name__)

    async def _repeat_unanswered(self, now: datetime) -> int:
        candidates = await self._deliveries.list_repeat_candidates(now, self._batch_size)
        for delivery, _reminder, occurrence in candidates:
            await self._deliveries.update_fields(
                delivery.id,
                status=DeliveryStatus.PENDING,
                next_attempt_at=now,
                locked_until=None,
            )
            await self._occurrences.bump_repeats(occurrence.id)
        return len(candidates)

    async def _purge_fsm_states(self, now: datetime) -> int:
        stmt = (
            sa.delete(FSMState)
            .where(FSMState.updated_at < now - self._fsm_ttl)
            .returning(FSMState.key)
        )
        return len((await self._session.execute(stmt)).scalars().all())
