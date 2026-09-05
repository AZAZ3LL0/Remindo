"""ops.monitor: read the queue, publish the report, alert on the edge (tech.md 24.3)."""

import math
from dataclasses import dataclass, field
from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.render.texts import T
from app.core.clock import Clock
from app.core.logging import get_logger
from app.db.repositories.deliveries import DeliveriesRepository
from app.domain.contracts import ErrorClass
from app.domain.ops import AlertKind, AlertState, OpsReport, build_report, decide_alert
from app.gateways.bot_gateway import BotGateway, OutgoingMessage, classify_error

_log = get_logger(__name__)

#: One message per edge, so the two kinds map onto two keys and nothing else.
_ALERT_KEYS = {
    AlertKind.RAISED: "ops.alert_lag",
    AlertKind.CLEARED: "ops.alert_cleared",
}


@dataclass(slots=True)
class MonitorState:
    """What the monitor remembers between ticks, owned by the worker process.

    It lives in memory rather than in a row because it belongs to the observer,
    not to the product: a restart resets it, the next tick raises the alert
    again if the lag is still there, and that costs one repeated message
    instead of a migration.
    """

    alert: AlertState = AlertState.CLEAR
    report: OpsReport | None = None
    #: Admins who blocked the bot. `users.is_blocked` is not touched: that flag
    #: belongs to reminder delivery, and an admin may have no row at all.
    muted_admins: frozenset[int] = field(default_factory=frozenset)


@dataclass(frozen=True, slots=True)
class MonitorResult:
    report: OpsReport
    state: AlertState
    notified: AlertKind | None = None
    recipients: int = 0


def render_alert(kind: AlertKind, report: OpsReport, lang: str) -> str:
    """The operator's one line.

    Minutes round up: a lag of 5.2 printed as 5 would read as if the threshold
    had not been crossed, right in the message saying it was.
    """
    return T(
        _ALERT_KEYS[kind],
        lang,
        lag=math.ceil(report.lag.total_seconds() / 60),
        queue=report.queue_size,
        errors=round(report.error_ratio * 100),
    )


class OpsService:
    def __init__(
        self,
        session: AsyncSession,
        clock: Clock,
        gateway: BotGateway,
        *,
        admin_ids: frozenset[int],
        alert_lag: timedelta,
        metrics_window: timedelta,
        lang: str,
    ) -> None:
        self._session = session
        self._clock = clock
        self._gateway = gateway
        self._admin_ids = admin_ids
        self._alert_lag = alert_lag
        self._metrics_window = metrics_window
        self._lang = lang
        self._deliveries = DeliveriesRepository(session)

    async def run(self, state: MonitorState) -> MonitorResult:
        """One tick. The state carries the edge across ticks and is updated here."""
        now = self._clock.now()
        snapshot = await self._deliveries.queue_snapshot(now, self._metrics_window)
        report = build_report(snapshot, now)
        state.report = report

        decision = decide_alert(state.alert, report.lag, self._alert_lag)
        if decision.notify is None:
            state.alert = decision.state
            return MonitorResult(report=report, state=decision.state)

        audience = self._admin_ids - state.muted_admins
        delivered = await self._notify(decision.notify, report, audience, state)
        if audience and delivered == 0:
            # Nobody heard it, so the edge has not been reported. Leaving the
            # old state lets the next tick try again a minute from now; there
            # is nothing to gain from retrying inside this one.
            _log.warning("ops.alert_undelivered", kind=decision.notify.value)
            return MonitorResult(report=report, state=state.alert)

        state.alert = decision.state
        _log.info(
            "ops.alert",
            kind=decision.notify.value,
            lag_seconds=int(report.lag.total_seconds()),
            queue_size=report.queue_size,
            error_ratio=round(report.error_ratio, 3),
            recipients=delivered,
        )
        return MonitorResult(
            report=report,
            state=decision.state,
            notified=decision.notify,
            recipients=delivered,
        )

    async def _notify(
        self,
        kind: AlertKind,
        report: OpsReport,
        audience: frozenset[int],
        state: MonitorState,
    ) -> int:
        """Message every admin, counting the ones that got through.

        A failure on one admin must not cost the others their warning, so each
        send stands on its own.
        """
        text = render_alert(kind, report, self._lang)
        delivered = 0
        for admin_id in sorted(audience):
            try:
                await self._gateway.send(
                    OutgoingMessage(chat_id=admin_id, text=text, keyboard=None)
                )
            except Exception as error:
                self._alert_failed(admin_id, error, state)
                continue
            delivered += 1
        return delivered

    def _alert_failed(self, admin_id: int, error: Exception, state: MonitorState) -> None:
        if classify_error(error) is ErrorClass.FORBIDDEN:
            state.muted_admins |= {admin_id}
            _log.warning("ops.alert_blocked", admin_id=admin_id)
            return
        _log.warning("ops.alert_failed", admin_id=admin_id, error=type(error).__name__)
