"""dispatcher.deliver cycle."""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.clock import Clock
from app.core.config import Settings
from app.gateways.bot_gateway import BotGateway
from app.services.dispatching import DispatchingService, DispatchResult


async def run_once(
    session_factory: async_sessionmaker[AsyncSession],
    clock: Clock,
    gateway: BotGateway,
    settings: Settings,
) -> DispatchResult:
    async with session_factory() as session:
        service = DispatchingService(
            session,
            clock,
            gateway,
            batch_size=settings.dispatch_batch_size,
            lock_seconds=settings.delivery_lock_seconds,
        )
        return await service.deliver()
