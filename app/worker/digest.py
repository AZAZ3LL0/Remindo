"""digest.send cycle."""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.clock import Clock
from app.core.config import Settings
from app.gateways.bot_gateway import BotGateway
from app.services.digest import DigestResult, DigestService


async def run_once(
    session_factory: async_sessionmaker[AsyncSession],
    clock: Clock,
    gateway: BotGateway,
    settings: Settings,
) -> DigestResult:
    async with session_factory() as session:
        return await DigestService(
            session,
            clock,
            gateway,
            weekday=settings.digest_weekday,
            hour=settings.digest_hour,
            batch_size=settings.digest_batch_size,
        ).run()
