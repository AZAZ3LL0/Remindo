"""digest.send: the weekly summary, once per user per week (tech.md 23.5)."""

from dataclasses import asdict, dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.render.stats import render_digest
from app.core.clock import Clock
from app.core.logging import get_logger
from app.db.models import User
from app.db.repositories.categories import CategoriesRepository
from app.db.repositories.users import UsersRepository
from app.domain.contracts import ErrorClass
from app.domain.digest import digest_due_at, digest_window
from app.domain.stats import StatsSummary
from app.gateways.bot_gateway import BotGateway, OutgoingMessage, classify_error
from app.services.recipients import quiet_hours_of
from app.services.stats import StatsService

_log = get_logger(__name__)

#: Failures that stop this week's digest for good. A retry-after or a transient
#: fault leaves the mark off instead, and the next tick tries again.
_TERMINAL_ERRORS = frozenset({ErrorClass.FORBIDDEN, ErrorClass.BAD_REQUEST})


@dataclass(frozen=True, slots=True)
class DigestResult:
    considered: int = 0
    sent: int = 0
    empty: int = 0
    blocked: int = 0
    failed: int = 0
    deferred: int = 0


class DigestService:
    def __init__(
        self,
        session: AsyncSession,
        clock: Clock,
        gateway: BotGateway,
        weekday: int,
        hour: int,
        batch_size: int = 100,
    ) -> None:
        self._session = session
        self._clock = clock
        self._gateway = gateway
        self._weekday = weekday
        self._hour = hour
        self._batch_size = batch_size
        self._users = UsersRepository(session)
        self._categories = CategoriesRepository(session)
        self._stats = StatsService(session, clock)

    async def run(self) -> DigestResult:
        now = self._clock.now()
        candidates = await self._users.list_digest_candidates(now, self._batch_size)

        result = DigestResult(considered=len(candidates))
        for user in candidates:
            result = _add(result, await self._one(user, now))
        _log.info("digest.send", **asdict(result))
        return result

    async def _one(self, user: User, now: datetime) -> DigestResult:
        """One user's digest, committed on its own.

        A failure on one recipient must not cost the rest of the batch their
        week: they had nothing to do with it, and the next tick is a minute
        away either way.
        """
        moment = digest_due_at(
            now,
            ZoneInfo(user.timezone),
            weekday=self._weekday,
            hour=self._hour,
            sent_at=user.digest_sent_at,
            quiet=quiet_hours_of(user),
        )
        if moment is None:
            return DigestResult(deferred=1)

        summary = await self._stats.summary_for(user, moment)
        if not summary.last_7_days.total:
            # Nothing happened, so there is nothing to report. The mark still
            # goes down, or the cycle would come back every minute all week.
            await self._mark(user.id, moment)
            return DigestResult(empty=1)

        return await self._send(user, summary, moment)

    async def _send(self, user: User, summary: StatsSummary, moment: datetime) -> DigestResult:
        tz = ZoneInfo(user.timezone)
        categories = await self._categories.list_by_ids(
            [entry.category_id for entry in summary.by_category]
        )
        text = render_digest(summary, digest_window(moment, tz), categories, tz, user.language)

        try:
            await self._gateway.send(
                OutgoingMessage(chat_id=user.tg_chat_id, text=text, keyboard=None)
            )
        except Exception as error:
            return await self._failed(user, moment, error)

        await self._mark(user.id, moment)
        return DigestResult(sent=1)

    async def _failed(self, user: User, moment: datetime, error: Exception) -> DigestResult:
        error_class = classify_error(error)
        if error_class not in _TERMINAL_ERRORS:
            # The send is the only write attempted so far, so leaving the mark
            # alone is all it takes: the next tick picks the same moment up.
            _log.warning("digest.deferred", user_id=user.id, error=type(error).__name__)
            return DigestResult(deferred=1)

        if error_class is ErrorClass.FORBIDDEN:
            await self._users.mark_blocked(user.id, True)
            await self._mark(user.id, moment)
            return DigestResult(blocked=1)

        _log.error("digest.failed", user_id=user.id, error=type(error).__name__)
        await self._mark(user.id, moment)
        return DigestResult(failed=1)

    async def _mark(self, user_id: int, moment: datetime) -> None:
        await self._users.mark_digest_sent(user_id, moment)
        await self._session.commit()


def _add(left: DigestResult, right: DigestResult) -> DigestResult:
    return DigestResult(
        considered=left.considered,
        sent=left.sent + right.sent,
        empty=left.empty + right.empty,
        blocked=left.blocked + right.blocked,
        failed=left.failed + right.failed,
        deferred=left.deferred + right.deferred,
    )
