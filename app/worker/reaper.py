"""reaper.sweep cycle."""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.clock import Clock
from app.gateways.bot_gateway import BotGateway
from app.services.dispatching import ReaperService, SweepResult


async def run_once(
    session_factory: async_sessionmaker[AsyncSession], clock: Clock, gateway: BotGateway
) -> SweepResult:
    async with session_factory() as session:
        return await ReaperService(session, clock, gateway).sweep()
