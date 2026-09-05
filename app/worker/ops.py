"""ops.monitor cycle."""

from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.clock import Clock
from app.core.config import Settings
from app.gateways.bot_gateway import BotGateway
from app.services.ops import MonitorResult, MonitorState, OpsService


async def run_once(
    session_factory: async_sessionmaker[AsyncSession],
    clock: Clock,
    gateway: BotGateway,
    settings: Settings,
    state: MonitorState,
) -> MonitorResult:
    """The state outlives the session on purpose: the alert edge is what makes
    the cycle idempotent, and it belongs to the process, not to a transaction."""
    async with session_factory() as session:
        return await OpsService(
            session,
            clock,
            gateway,
            admin_ids=settings.admin_ids,
            alert_lag=timedelta(minutes=settings.alert_lag_minutes),
            metrics_window=timedelta(minutes=settings.metrics_window_minutes),
            lang=settings.default_language,
        ).run(state)
