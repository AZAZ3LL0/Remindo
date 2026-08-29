"""planner.materialize cycle."""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.clock import Clock
from app.core.config import Settings
from app.services.planning import PlanningResult, PlanningService


async def run_once(
    session_factory: async_sessionmaker[AsyncSession], clock: Clock, settings: Settings
) -> PlanningResult:
    async with session_factory() as session:
        service = PlanningService(
            session,
            clock,
            horizon_hours=settings.planner_horizon_hours,
            occurrence_ttl_minutes=settings.occurrence_ttl_minutes,
        )
        return await service.materialize()
