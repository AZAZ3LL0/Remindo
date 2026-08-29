"""/stats."""

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.render.stats import render_stats
from app.core.clock import Clock
from app.db.models import User
from app.services.stats import StatsService

router = Router(name="stats")


@router.message(Command("stats"))
async def handle_stats(message: Message, user: User, session: AsyncSession, clock: Clock) -> None:
    summary = await StatsService(session, clock).summary(user.id)
    await message.answer(render_stats(summary, user.language))
