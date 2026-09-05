"""/list and /today: the two lists a user reads (tech.md 21.1, 21.9)."""

from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, StateFilter
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.callbacks import NO_CATEGORY_FILTER, ListCb, PageCb, RemCb, WizCb
from app.bot.keyboards.pagination import PageItem, page_count
from app.bot.keyboards.reminders import reminder_filter_kb, reminder_list_kb, today_kb
from app.bot.render.lists import render_reminder_list
from app.bot.render.texts import T
from app.bot.render.today import render_today
from app.core.clock import Clock
from app.db.models import User
from app.db.repositories.categories import CategoriesRepository
from app.db.repositories.occurrences import OccurrencesRepository
from app.services.categories import CategoriesService
from app.services.reminders import RemindersService
from app.services.today import TodayService

router = Router(name="lists")

PAGE_SIZE = 8

Screen = tuple[str, InlineKeyboardMarkup]


async def render_list(
    user: User, session: AsyncSession, clock: Clock, page: int, category_id: int
) -> Screen:
    """One page of the reminder list, filtered or not.

    Public because the card returns here after a pause, a resume or a delete:
    the screen the user came from is the screen they should land back on.
    """
    chosen = category_id if category_id != NO_CATEGORY_FILTER else None
    reminders, total = await RemindersService(session, clock).list_for_owner(
        user.id, page=page, page_size=PAGE_SIZE, category_id=chosen
    )
    categories = CategoriesRepository(session)
    occurrences = OccurrencesRepository(session)
    now = clock.now()

    rows = []
    buttons = []
    for reminder in reminders:
        category = await categories.get_by_id(reminder.category_id)
        if category is None:
            continue
        rows.append((reminder, category, await occurrences.next_fire_at(reminder.id, now)))
        buttons.append(
            PageItem(
                text=f"{category.emoji} {reminder.title}",
                callback_data=RemCb(reminder_id=reminder.id, action="open").pack(),
            )
        )

    filter_title = None
    if chosen is not None:
        current = await categories.get_by_id(chosen)
        filter_title = None if current is None else f"{current.emoji} {current.title}"

    text = render_reminder_list(
        rows,
        page=page,
        total=total,
        tz=ZoneInfo(user.timezone),
        page_size=PAGE_SIZE,
        lang=user.language,
        filter_title=filter_title,
    )
    keyboard = reminder_list_kb(
        buttons,
        category_id=category_id,
        page=page,
        total_pages=page_count(total, PAGE_SIZE),
        lang=user.language,
    )
    return text, keyboard


@router.message(Command("list"))
async def handle_list(message: Message, user: User, session: AsyncSession, clock: Clock) -> None:
    text, keyboard = await render_list(user, session, clock, 0, NO_CATEGORY_FILTER)
    await message.answer(text, reply_markup=keyboard)


@router.callback_query(StateFilter(None), ListCb.filter())
async def handle_page(
    query: CallbackQuery,
    callback_data: ListCb,
    user: User,
    session: AsyncSession,
    clock: Clock,
) -> None:
    """Paging and filtering are the same screen, so they are the same handler."""
    text, keyboard = await render_list(
        user, session, clock, callback_data.page, callback_data.category_id
    )
    await query.answer()
    await show(query, text, keyboard)


@router.callback_query(StateFilter(None), WizCb.filter(F.step == "filter"))
async def handle_filter(
    query: CallbackQuery,
    callback_data: WizCb,
    user: User,
    session: AsyncSession,
    clock: Clock,
) -> None:
    current = int(callback_data.value) if callback_data.value.isdigit() else NO_CATEGORY_FILTER
    categories = await CategoriesService(session, clock).list_for_user(user.id)
    await query.answer()
    await show(
        query,
        T("list.filter", user.language, title=T("list.filter_all", user.language)),
        reminder_filter_kb(categories, current, user.language),
    )


@router.message(Command("today"))
async def handle_today(message: Message, user: User, session: AsyncSession, clock: Clock) -> None:
    text, keyboard = await _today_screen(user, session, clock, page=0)
    await message.answer(text, reply_markup=keyboard)


@router.callback_query(StateFilter(None), PageCb.filter(F.scope == "today"))
async def handle_today_page(
    query: CallbackQuery,
    callback_data: PageCb,
    user: User,
    session: AsyncSession,
    clock: Clock,
) -> None:
    text, keyboard = await _today_screen(user, session, clock, callback_data.page)
    await query.answer()
    await show(query, text, keyboard)


async def _today_screen(user: User, session: AsyncSession, clock: Clock, page: int) -> Screen:
    entries, total = await TodayService(session, clock).list_for_user(
        user, page=page, page_size=PAGE_SIZE
    )
    text = render_today(entries, total, ZoneInfo(user.timezone), user.language)
    return text, today_kb(page, page_count(total, PAGE_SIZE), user.language)


async def show(query: CallbackQuery, text: str, keyboard: InlineKeyboardMarkup | None) -> None:
    """Redraw the screen in place.

    A press that changes nothing produces an identical message, and Telegram
    answers that with `message is not modified`. The screen is already right in
    that case, so the error is the expected outcome, not a failure.
    """
    if not isinstance(query.message, Message):
        return
    try:
        await query.message.edit_text(text, reply_markup=keyboard)
    except TelegramBadRequest as error:
        if "message is not modified" not in str(error):
            raise
