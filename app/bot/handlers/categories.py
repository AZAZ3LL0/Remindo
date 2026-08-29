"""/categories: what the user can attach a reminder to."""

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.pickers import category_picker_kb
from app.bot.render.texts import T
from app.core.clock import Clock
from app.db.models import User
from app.services.categories import CategoriesService

router = Router(name="categories")


@router.message(Command("categories"))
async def handle_categories(
    message: Message, user: User, session: AsyncSession, clock: Clock
) -> None:
    categories = await CategoriesService(session, clock).list_for_user(user.id)
    if not categories:
        await message.answer(T("categories.empty", user.language))
        return
    await message.answer(
        T("categories.title", user.language),
        reply_markup=category_picker_kb(categories, page=0, lang=user.language),
    )
