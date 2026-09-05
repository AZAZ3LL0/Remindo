"""dispatcher.deliver: claim, send, apply the retry policy (tech.md 7.2)."""

from collections import Counter
from dataclasses import asdict, dataclass
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
from app.db.repositories.deliveries import DeliveriesRepository
from app.db.repositories.occurrences import OccurrencesRepository
from app.db.repositories.users import UsersRepository
from app.domain.contracts import ActionKind, DeliveryStatus, OccurrenceStatus
from app.domain.dispatching import (
    AbortReason,
    Verdict,
    check_deliverable,
    decide_abort,
    decide_failure,
    decide_success,
)
from app.domain.sweeping import decide_repeat, is_overdue
from app.gateways.bot_gateway import (
    BotGateway,
    MessageRef,
    OutgoingMessage,
    classify_error,
    retry_after_seconds,
)
from app.services.recipients import quiet_hours_of

_log = get_logger(__name__)

#: Occurrence statuses a successful send moves to `sent`. Anything else was
#: already resolved by a reaction or by the reaper.
_SENDABLE_OCCURRENCE_STATUSES = (OccurrenceStatus.PENDING, OccurrenceStatus.DISPATCHING)

#: Occurrence, reminder, category and recipient of one delivery.
SendContext = tuple[Occurrence, Reminder, Category, User]


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
        self._users = UsersRepository(session)

    async def deliver(self) -> DispatchResult:
        """One dispatcher cycle. Delivery is at-least-once by design."""
        now = self._clock.now()
        claimed = await self._deliveries.claim_due(now, self._lock, self._batch_size)
        # The lease is committed before any network call, so a crash mid-send
        # cannot hand the same row to another worker before it expires.
        await self._session.commit()

        context = await self._deliveries.load_send_context([row.id for row in claimed])
        counts: Counter[DeliveryStatus] = Counter()
        for delivery in claimed:
            counts[await self._deliver_one(delivery, context.get(delivery.id))] += 1

        result = DispatchResult(
            claimed=len(claimed),
            sent=counts[DeliveryStatus.SENT],
            retried=counts[DeliveryStatus.PENDING],
            failed=counts[DeliveryStatus.FAILED],
            blocked=counts[DeliveryStatus.BLOCKED],
        )
        _log.info("dispatcher.deliver", **asdict(result))
        return result

    async def _deliver_one(self, delivery: Delivery, context: SendContext | None) -> DeliveryStatus:
        if context is None:
            # The row lost its reminder or recipient between the claim and this
            # load: an account deletion cascading while the batch was in flight.
            return await self._apply(
                delivery, decide_abort(AbortReason.CONTEXT_MISSING, delivery.attempts)
            )

        occurrence, reminder, category, user = context
        abort = check_deliverable(occurrence.status, user_blocked=user.is_blocked)
        if abort is not None:
            _log.info("dispatcher.aborted", delivery_id=delivery.id, reason=abort.value)
            return await self._apply(delivery, decide_abort(abort, delivery.attempts))

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
            verdict = decide_failure(
                delivery.attempts,
                classify_error(error),
                self._clock.now(),
                error_code=type(error).__name__,
                retry_after=retry_after_seconds(error),
            )
            _log.warning(
                "dispatcher.send_failed",
                delivery_id=delivery.id,
                user_id=delivery.user_id,
                error=verdict.error_code,
                status=verdict.status.value,
            )
            return await self._apply(delivery, verdict)

        return await self._apply(delivery, decide_success(), occurrence=occurrence, ref=ref)

    async def _apply(
        self,
        delivery: Delivery,
        verdict: Verdict,
        occurrence: Occurrence | None = None,
        ref: MessageRef | None = None,
    ) -> DeliveryStatus:
        """Write one verdict back and release the lease."""
        values: dict[str, object] = {
            "status": verdict.status,
            "attempts": verdict.attempts,
            "error_code": verdict.error_code,
            "locked_until": None,
        }
        if verdict.next_attempt_at is not None:
            values["next_attempt_at"] = verdict.next_attempt_at
        if ref is not None:
            values["sent_at"] = self._clock.now()
            values["tg_message_id"] = ref.message_id

        await self._deliveries.update_fields(delivery.id, **values)
        if verdict.blocks_user:
            await self._users.mark_blocked(delivery.user_id, True)
        if occurrence is not None and occurrence.status in _SENDABLE_OCCURRENCE_STATUSES:
            await self._occurrences.set_status(occurrence.id, OccurrenceStatus.SENT)
        await self._session.commit()
        return verdict.status


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
        _log.info("reaper.sweep", **asdict(result))
        return result

    async def _expire_overdue(self, now: datetime) -> int:
        # The query narrows the batch; the rule itself is checked in the domain,
        # so an occurrence somebody answered is never overwritten with silence.
        overdue = [
            occurrence
            for occurrence in await self._occurrences.list_expired(now, self._batch_size)
            if is_overdue(occurrence.status, occurrence.expires_at, now)
        ]
        for occurrence in overdue:
            for delivery in await self._deliveries.list_sent_for_occurrence(occurrence.id):
                await self._deliveries.add_action(
                    delivery.id, delivery.user_id, ActionKind.AUTO_EXPIRE, created_at=now
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
        # The budget is read once per sweep: a shared reminder hands the same
        # occurrence back for every recipient, and bumping it in the loop would
        # make the second recipient look like a second repeat.
        budget = {occurrence.id: occurrence.repeats_sent for _, _, occurrence, _ in candidates}
        repeated = 0
        bumped: set[int] = set()
        for delivery, reminder, occurrence, user in candidates:
            plan = decide_repeat(
                sent_at=delivery.sent_at,
                repeat_after_minutes=reminder.repeat_after_minutes,
                repeats_sent=budget[occurrence.id],
                max_repeats=reminder.max_repeats,
                expires_at=occurrence.expires_at,
                quiet=quiet_hours_of(user),
                now=now,
            )
            if plan is None:
                continue
            await self._deliveries.update_fields(
                delivery.id,
                status=DeliveryStatus.PENDING,
                next_attempt_at=plan.next_attempt_at,
                locked_until=None,
            )
            if occurrence.id not in bumped:
                # One sweep costs one repeat however many recipients it reaches:
                # the budget lives on the occurrence (tech.md 4.2), not on a
                # delivery. It is spent when the repeat is queued, not when it
                # lands, or one silent night would queue every repeat at once.
                await self._occurrences.bump_repeats(occurrence.id)
                bumped.add(occurrence.id)
            repeated += 1
        return repeated

    async def _purge_fsm_states(self, now: datetime) -> int:
        stmt = (
            sa.delete(FSMState)
            .where(FSMState.updated_at < now - self._fsm_ttl)
            .returning(FSMState.key)
        )
        return len((await self._session.execute(stmt)).scalars().all())
