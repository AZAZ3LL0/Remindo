"""/list with pagination."""

from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.callbacks import PageCb, RemCb
from app.bot.keyboards.pagination import PageItem, page_count, paginated_kb
from app.bot.render.lists import render_reminder_list
from app.core.clock import Clock
from app.db.models import User
from app.db.repositories.categories import CategoriesRepository
from app.db.repositories.occurrences import OccurrencesRepository
from app.services.reminders import RemindersService

router = Router(name="lists")

PAGE_SIZE = 8


async def _render_page(
    user: User, session: AsyncSession, clock: Clock, page: int
) -> tuple[str, object]:
    reminders, total = await RemindersService(session, clock).list_for_owner(
        user.id, page=page, page_size=PAGE_SIZE
    )
    categories = CategoriesRepository(session)
    occurrences = OccurrencesRepository(session)
    now = clock.now()

    rows = []
    buttons = []
    for reminder in reminders:
        category = await categories.get_by_id(reminder.category_id)
        next_fire = await occurrences.next_fire_at(reminder.id, now)
        if category is None:
            continue
        rows.append((reminder, category, next_fire))
        buttons.append(
            PageItem(
                text=f"{category.emoji} {reminder.title}",
                callback_data=RemCb(reminder_id=reminder.id, action="open").pack(),
            )
        )

    text = render_reminder_list(
        rows,
        page=page,
        total=total,
        tz=ZoneInfo(user.timezone),
        page_size=PAGE_SIZE,
        lang=user.language,
    )
    keyboard = paginated_kb(
        buttons,
        scope="rem",
        page=page,
        total_pages=page_count(total, PAGE_SIZE),
        lang=user.language,
    )
    return text, keyboard


@router.message(Command("list"))
async def handle_list(message: Message, user: User, session: AsyncSession, clock: Clock) -> None:
    text, keyboard = await _render_page(user, session, clock, page=0)
    await message.answer(text, reply_markup=keyboard)  # type: ignore[arg-type]


@router.callback_query(PageCb.filter(F.scope == "rem"))
async def handle_page(
    query: CallbackQuery,
    callback_data: PageCb,
    user: User,
    session: AsyncSession,
    clock: Clock,
) -> None:
    text, keyboard = await _render_page(user, session, clock, page=callback_data.page)
    await query.answer()
    if isinstance(query.message, Message):
        await query.message.edit_text(text, reply_markup=keyboard)  # type: ignore[arg-type]
