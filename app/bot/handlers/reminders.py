"""Reminder creation wizard. Reference slice: an interval reminder (water)."""

from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.callbacks import CatCb, WizCb
from app.bot.fsm.reminder_wizard import ReminderWizard
from app.bot.keyboards.confirm import confirm_kb
from app.bot.keyboards.pickers import category_picker_kb, interval_picker_kb, window_picker_kb
from app.bot.render.reminder import render_reminder_card
from app.bot.render.texts import T
from app.core.clock import Clock
from app.db.models import User
from app.db.repositories.categories import CategoriesRepository
from app.domain.errors import ValidationError
from app.domain.schedules import IntervalSchedule
from app.services.categories import CategoriesService
from app.services.reminders import TITLE_MAX_LENGTH, RemindersService

router = Router(name="reminders")


@router.message(Command("new"))
async def handle_new(
    message: Message, user: User, session: AsyncSession, clock: Clock, state: FSMContext
) -> None:
    categories = await CategoriesService(session, clock).list_for_user(user.id)
    await state.set_state(ReminderWizard.category)
    await message.answer(
        T("wizard.pick_category", user.language),
        reply_markup=category_picker_kb(categories, page=0, lang=user.language),
    )


@router.callback_query(ReminderWizard.category, CatCb.filter(F.action == "pick"))
async def handle_category(
    query: CallbackQuery, callback_data: CatCb, user: User, state: FSMContext
) -> None:
    await state.update_data(category_id=callback_data.category_id)
    await state.set_state(ReminderWizard.title)
    await query.answer()
    if query.message is not None:
        await query.message.answer(T("wizard.ask_title", user.language))


@router.message(ReminderWizard.title)
async def handle_title(message: Message, user: User, state: FSMContext) -> None:
    title = (message.text or "").strip()
    if not 1 <= len(title) <= TITLE_MAX_LENGTH:
        await message.answer(T("wizard.title_invalid", user.language))
        return
    await state.update_data(title=title)
    await state.set_state(ReminderWizard.every_minutes)
    await message.answer(
        T("wizard.ask_interval", user.language), reply_markup=interval_picker_kb(user.language)
    )


@router.callback_query(ReminderWizard.every_minutes, WizCb.filter(F.step == "every"))
async def handle_interval(
    query: CallbackQuery, callback_data: WizCb, user: User, state: FSMContext
) -> None:
    if not callback_data.value.isdigit():
        await query.answer()
        return
    await state.update_data(every_minutes=int(callback_data.value))
    await state.set_state(ReminderWizard.window)
    await query.answer()
    if query.message is not None:
        await query.message.answer(
            T("wizard.ask_window", user.language), reply_markup=window_picker_kb(user.language)
        )


@router.callback_query(ReminderWizard.window, WizCb.filter(F.step == "window"))
async def handle_window(
    query: CallbackQuery, callback_data: WizCb, user: User, state: FSMContext
) -> None:
    raw = callback_data.value
    if len(raw) != 8 or not raw.isdigit():
        await query.answer()
        return
    window_start = f"{raw[0:2]}:{raw[2:4]}"
    window_end = f"{raw[4:6]}:{raw[6:8]}"
    data = await state.update_data(window_start=window_start, window_end=window_end)
    await state.set_state(ReminderWizard.confirm)
    await query.answer()
    if query.message is not None:
        await query.message.answer(
            T(
                "wizard.confirm_interval",
                user.language,
                title=data["title"],
                every_minutes=data["every_minutes"],
                window_start=window_start,
                window_end=window_end,
            ),
            reply_markup=confirm_kb("create", 0, user.language),
        )


@router.callback_query(ReminderWizard.confirm, WizCb.filter(F.step == "confirm"))
async def handle_confirm(
    query: CallbackQuery,
    callback_data: WizCb,
    user: User,
    session: AsyncSession,
    clock: Clock,
    state: FSMContext,
) -> None:
    if callback_data.value != "yes":
        await state.clear()
        await query.answer(T("wizard.cancelled", user.language))
        return

    data = await state.get_data()
    schedule = IntervalSchedule(
        every_minutes=data["every_minutes"],
        window_start=data["window_start"],
        window_end=data["window_end"],
    )
    service = RemindersService(session, clock)
    try:
        reminder = await service.create(
            owner_id=user.id,
            category_id=data["category_id"],
            title=data["title"],
            schedule=schedule,
            timezone=user.timezone,
        )
    except ValidationError:
        await query.answer(T("error.generic", user.language), show_alert=True)
        return

    category = await CategoriesRepository(session).get_by_id(reminder.category_id)
    await state.clear()
    await query.answer(T("wizard.created", user.language))
    if query.message is not None and category is not None:
        await query.message.answer(
            render_reminder_card(reminder, category, None, ZoneInfo(user.timezone), user.language)
        )
