"""/stats: the streak and the completion rate, whole and per category."""

from aiogram import Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.callbacks import NO_CATEGORY_FILTER, StatCb
from app.bot.handlers.lists import PAGE_SIZE, show
from app.bot.keyboards.pagination import PageItem, page_count
from app.bot.keyboards.stats import stats_card_kb, stats_kb
from app.bot.render.stats import render_stats, render_stats_card
from app.core.clock import Clock
from app.db.models import User
from app.db.repositories.categories import CategoriesRepository
from app.domain.errors import NotFoundError
from app.services.stats import StatsService

router = Router(name="stats")

Screen = tuple[str, InlineKeyboardMarkup]


async def stats_screen(
    user: User, session: AsyncSession, clock: Clock, category_id: int, page: int
) -> Screen:
    """The whole picture, or one category's slice."""
    if category_id != NO_CATEGORY_FILTER:
        return await _card(user, session, clock, category_id)

    summary = await StatsService(session, clock).summary(user.id)
    categories = await CategoriesRepository(session).list_by_ids(
        [entry.category_id for entry in summary.by_category]
    )

    # Only the categories still readable become rows: a breakdown entry whose
    # category was deleted has nothing to be labelled with, and a button
    # leading to a card that cannot be drawn is worse than no button.
    rows = [entry for entry in summary.by_category if entry.category_id in categories]
    total_pages = page_count(len(rows), PAGE_SIZE)
    page = min(max(page, 0), total_pages - 1)
    window = rows[page * PAGE_SIZE : (page + 1) * PAGE_SIZE]

    buttons = [
        PageItem(
            text=f"{categories[entry.category_id].emoji} {categories[entry.category_id].title}",
            callback_data=StatCb(category_id=entry.category_id, page=0).pack(),
        )
        for entry in window
    ]
    text = render_stats(summary, categories, user.language)
    return text, stats_kb(buttons, page, total_pages, user.language)


async def _card(user: User, session: AsyncSession, clock: Clock, category_id: int) -> Screen:
    category = await CategoriesRepository(session).get_by_id(category_id)
    if category is None:
        raise NotFoundError(f"category {category_id} not found")

    summary = await StatsService(session, clock).summary(user.id, category_id)
    return render_stats_card(summary, category, user.language), stats_card_kb(user.language)


@router.message(Command("stats"))
async def handle_stats(
    message: Message, user: User, session: AsyncSession, clock: Clock, state: FSMContext
) -> None:
    await state.clear()
    text, keyboard = await stats_screen(user, session, clock, NO_CATEGORY_FILTER, page=0)
    await message.answer(text, reply_markup=keyboard)


@router.callback_query(StateFilter(None), StatCb.filter())
async def handle_stats_page(
    query: CallbackQuery,
    callback_data: StatCb,
    user: User,
    session: AsyncSession,
    clock: Clock,
) -> None:
    """Paging and drilling into a category are the same screen, so they are the
    same handler, the way the reminder list pages and filters in one."""
    text, keyboard = await stats_screen(
        user, session, clock, callback_data.category_id, callback_data.page
    )
    await query.answer()
    await show(query, text, keyboard)
