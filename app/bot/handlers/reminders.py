"""/new: the reminder creation wizard (tech.md 15, S3).

Category, title and schedule kind, then a branch per kind, then one shared
confirmation. Each step writes into FSM data and nothing else; the row appears
only when the user confirms.
"""

from datetime import date, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.callbacks import CatCb, WizCb, unpack_wall_time, unpack_window
from app.bot.fsm.reminder_wizard import ReminderWizard
from app.bot.keyboards.confirm import confirm_kb
from app.bot.keyboards.pickers import category_picker_kb
from app.bot.keyboards.wizard import (
    MISSING_DAY_ATOMS,
    daily_times_kb,
    date_picker_kb,
    interval_kb,
    missing_day_kb,
    monthday_kb,
    once_time_kb,
    schedule_kind_kb,
    weekly_days_kb,
    window_kb,
)
from app.bot.render.reminder import render_reminder_card
from app.bot.render.texts import Lang, T
from app.bot.render.wizard import (
    render_confirmation,
    render_month_days,
    render_times,
    render_weekdays,
)
from app.core.clock import Clock
from app.db.models import User
from app.db.repositories.categories import CategoriesRepository
from app.domain.contracts import ScheduleKind
from app.domain.errors import ScheduleExhaustedError, ValidationError
from app.domain.onboarding import parse_wall_time
from app.domain.reminders import (
    build_daily_schedule,
    build_interval_schedule,
    build_monthly_schedule,
    build_once_schedule,
    build_weekly_schedule,
    local_today,
    normalize_reminder_title,
    parse_user_date,
    parse_user_interval,
    parse_user_window,
)
from app.domain.schedules import (
    INTERVAL_MAX_MINUTES,
    INTERVAL_MIN_MINUTES,
    TIMES_MAX_LENGTH,
    WINDOW_ATOM_LENGTH,
    Schedule,
    dump_schedule,
    format_hhmm,
    format_local_date,
    parse_hhmm,
    parse_local_date,
    parse_schedule,
)
from app.services.categories import CategoriesService
from app.services.reminders import RemindersService

router = Router(name="reminders")

#: FSM keys holding what the wizard has collected so far. The finished payload
#: lands under `schedule`, which is what the confirmation step reads: by then
#: the branch the user took no longer matters.
CATEGORY_ID_KEY = "category_id"
TITLE_KEY = "title"
KIND_KEY = "kind"
DATE_KEY = "date"
TIMES_KEY = "times"
WEEKDAYS_KEY = "weekdays"
MONTH_DAYS_KEY = "month_days"
ON_MISSING_KEY = "on_missing"
SCHEDULE_KEY = "schedule"
EVERY_MINUTES_KEY = "every_minutes"

Screen = tuple[str, InlineKeyboardMarkup | None]


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
    await state.update_data({CATEGORY_ID_KEY: callback_data.category_id})
    await state.set_state(ReminderWizard.title)
    await query.answer()
    await _show(query, T("wizard.ask_title", user.language), None)


@router.message(ReminderWizard.title)
async def handle_title(message: Message, user: User, state: FSMContext) -> None:
    try:
        title = normalize_reminder_title(message.text or "")
    except ValidationError:
        await message.answer(T("wizard.title_invalid", user.language))
        return

    await state.update_data({TITLE_KEY: title})
    await state.set_state(ReminderWizard.kind)
    await message.answer(
        T("wizard.pick_kind", user.language), reply_markup=schedule_kind_kb(user.language)
    )


@router.callback_query(ReminderWizard.kind, WizCb.filter(F.step == "kind"))
async def handle_kind(
    query: CallbackQuery, callback_data: WizCb, user: User, state: FSMContext
) -> None:
    try:
        kind = ScheduleKind(callback_data.value)
    except ValueError:
        await query.answer()
        return

    await state.update_data({KIND_KEY: kind.value})

    screen: Screen
    if kind is ScheduleKind.ONCE:
        await state.set_state(ReminderWizard.date)
        screen = (T("wizard.ask_date", user.language), date_picker_kb(user.language))
    elif kind is ScheduleKind.DAILY:
        await state.update_data({TIMES_KEY: []})
        await state.set_state(ReminderWizard.times)
        screen = _times_screen([], user.language)
    elif kind is ScheduleKind.WEEKLY:
        await state.update_data({WEEKDAYS_KEY: []})
        await state.set_state(ReminderWizard.weekdays)
        screen = _weekdays_screen([], user.language)
    elif kind is ScheduleKind.MONTHLY:
        await state.update_data({MONTH_DAYS_KEY: []})
        await state.set_state(ReminderWizard.month_days)
        screen = _month_days_screen([], user.language)
    else:
        await state.set_state(ReminderWizard.every_minutes)
        screen = (T("wizard.ask_interval", user.language), interval_kb(user.language))

    await query.answer()
    await _show(query, *screen)


@router.callback_query(ReminderWizard.date, WizCb.filter(F.step == "date"))
async def handle_date(
    query: CallbackQuery, callback_data: WizCb, user: User, clock: Clock, state: FSMContext
) -> None:
    if callback_data.value == "man":
        await query.answer()
        await _show(query, T("wizard.date_manual", user.language), None)
        return

    today = local_today(clock.now(), ZoneInfo(user.timezone))
    offsets = {"today": 0, "tmrw": 1}
    try:
        if callback_data.value in offsets:
            day = today + timedelta(days=offsets[callback_data.value])
        else:
            day = parse_user_date(callback_data.value, today)
    except ValidationError:
        await query.answer(T("wizard.date_invalid", user.language), show_alert=True)
        return

    await _remember_date(state, day)
    await query.answer()
    await _show(query, T("wizard.ask_at", user.language), once_time_kb(user.language))


@router.message(ReminderWizard.date)
async def handle_date_text(message: Message, user: User, clock: Clock, state: FSMContext) -> None:
    today = local_today(clock.now(), ZoneInfo(user.timezone))
    try:
        day = parse_user_date(message.text or "", today)
    except ValidationError:
        await message.answer(T("wizard.date_invalid", user.language))
        return

    await _remember_date(state, day)
    await message.answer(
        T("wizard.ask_at", user.language), reply_markup=once_time_kb(user.language)
    )


@router.callback_query(ReminderWizard.at, WizCb.filter(F.step == "at"))
async def handle_at(
    query: CallbackQuery, callback_data: WizCb, user: User, state: FSMContext
) -> None:
    if callback_data.value == "man":
        await query.answer()
        await _show(query, T("wizard.time_manual", user.language), None)
        return

    at = _preset_time(callback_data.value)
    if at is None:
        await query.answer()
        return

    await query.answer()
    await _show(query, *await _finish_once(state, at, user.language))


@router.message(ReminderWizard.at)
async def handle_at_text(message: Message, user: User, state: FSMContext) -> None:
    try:
        at = parse_wall_time(message.text or "")
    except ValidationError:
        await message.answer(T("wizard.time_invalid", user.language))
        return

    text, keyboard = await _finish_once(state, at, user.language)
    await message.answer(text, reply_markup=keyboard)


@router.callback_query(ReminderWizard.times, WizCb.filter(F.step == "time"))
async def handle_daily_time(
    query: CallbackQuery, callback_data: WizCb, user: User, state: FSMContext
) -> None:
    if callback_data.value == "man":
        await query.answer()
        await _show(query, T("wizard.time_manual", user.language), None)
        return

    preset = _preset_time(callback_data.value)
    if preset is None:
        await query.answer()
        return

    value = format_hhmm(preset)
    times = _stored_times(await state.get_data())
    if value not in times and len(times) >= TIMES_MAX_LENGTH:
        await query.answer(
            T("wizard.times_full", user.language, limit=TIMES_MAX_LENGTH), show_alert=True
        )
        return

    times = _toggle(times, value)
    await state.update_data({TIMES_KEY: times})
    await query.answer()
    await _show(query, *_times_screen(times, user.language))


@router.message(ReminderWizard.times)
async def handle_daily_time_text(message: Message, user: User, state: FSMContext) -> None:
    try:
        value = format_hhmm(parse_wall_time(message.text or ""))
    except ValidationError:
        await message.answer(T("wizard.time_invalid", user.language))
        return

    times = _stored_times(await state.get_data())
    if value not in times and len(times) >= TIMES_MAX_LENGTH:
        await message.answer(T("wizard.times_full", user.language, limit=TIMES_MAX_LENGTH))
        return

    times = _toggle(times, value)
    await state.update_data({TIMES_KEY: times})
    text, keyboard = _times_screen(times, user.language)
    await message.answer(text, reply_markup=keyboard)


@router.callback_query(ReminderWizard.times, WizCb.filter(F.step == "times"))
async def handle_times_done(query: CallbackQuery, user: User, state: FSMContext) -> None:
    """Ends the daily, weekly and monthly branches alike.

    Which kind is being built comes out of FSM data, not out of the screen: the
    times question is one question, and the days were already answered.
    """
    data = await state.get_data()
    if not _stored_times(data):
        await query.answer(T("wizard.times_empty", user.language), show_alert=True)
        return

    await query.answer()
    await _show(query, *await _to_confirmation(state, _schedule_from(data), user.language))


@router.callback_query(ReminderWizard.weekdays, WizCb.filter(F.step == "wday"))
async def handle_weekdays(
    query: CallbackQuery, callback_data: WizCb, user: User, state: FSMContext
) -> None:
    days = _stored_days(await state.get_data(), WEEKDAYS_KEY)

    if callback_data.value == "ok":
        if not days:
            await query.answer(T("wizard.weekdays_empty", user.language), show_alert=True)
            return
        await state.update_data({TIMES_KEY: []})
        await state.set_state(ReminderWizard.times)
        await query.answer()
        await _show(query, *_times_screen([], user.language))
        return

    if not callback_data.value.isdigit():
        await query.answer()
        return

    days = _toggle_day(days, int(callback_data.value))
    await state.update_data({WEEKDAYS_KEY: days})
    await query.answer()
    await _show(query, *_weekdays_screen(days, user.language))


@router.callback_query(ReminderWizard.month_days, WizCb.filter(F.step == "mday"))
async def handle_month_days(
    query: CallbackQuery, callback_data: WizCb, user: User, state: FSMContext
) -> None:
    days = _stored_days(await state.get_data(), MONTH_DAYS_KEY)

    if callback_data.value == "ok":
        if not days:
            await query.answer(T("wizard.mdays_empty", user.language), show_alert=True)
            return
        await state.set_state(ReminderWizard.on_missing)
        await query.answer()
        await _show(
            query, T("wizard.ask_missing_day", user.language), missing_day_kb(user.language)
        )
        return

    if not callback_data.value.isdigit():
        await query.answer()
        return

    days = _toggle_day(days, int(callback_data.value))
    await state.update_data({MONTH_DAYS_KEY: days})
    await query.answer()
    await _show(query, *_month_days_screen(days, user.language))


@router.callback_query(ReminderWizard.on_missing, WizCb.filter(F.step == "miss"))
async def handle_missing_day(
    query: CallbackQuery, callback_data: WizCb, user: User, state: FSMContext
) -> None:
    rule = MISSING_DAY_ATOMS.get(callback_data.value)
    if rule is None:
        await query.answer()
        return

    await state.update_data({ON_MISSING_KEY: rule, TIMES_KEY: []})
    await state.set_state(ReminderWizard.times)
    await query.answer()
    await _show(query, *_times_screen([], user.language))


@router.callback_query(ReminderWizard.every_minutes, WizCb.filter(F.step == "every"))
async def handle_interval(
    query: CallbackQuery, callback_data: WizCb, user: User, state: FSMContext
) -> None:
    if callback_data.value == "man":
        await query.answer()
        await _show(query, T("wizard.interval_manual", user.language), None)
        return

    if not callback_data.value.isdigit():
        await query.answer()
        return

    await query.answer()
    await _show(query, *await _ask_window(state, int(callback_data.value), user.language))


@router.message(ReminderWizard.every_minutes)
async def handle_interval_text(message: Message, user: User, state: FSMContext) -> None:
    try:
        minutes = parse_user_interval(message.text or "")
    except ValidationError:
        await message.answer(
            T(
                "wizard.interval_invalid",
                user.language,
                minimum=INTERVAL_MIN_MINUTES,
                maximum=INTERVAL_MAX_MINUTES,
            )
        )
        return

    text, keyboard = await _ask_window(state, minutes, user.language)
    await message.answer(text, reply_markup=keyboard)


@router.callback_query(ReminderWizard.window, WizCb.filter(F.step == "window"))
async def handle_window(
    query: CallbackQuery, callback_data: WizCb, user: User, state: FSMContext
) -> None:
    if callback_data.value == "man":
        await query.answer()
        await _show(query, T("wizard.window_manual", user.language), None)
        return

    raw = callback_data.value
    if len(raw) != WINDOW_ATOM_LENGTH or not raw.isdigit():
        await query.answer()
        return

    start, end = unpack_window(raw)
    try:
        window = parse_hhmm(start), parse_hhmm(end)
    except ValueError:
        await query.answer()
        return

    await query.answer()
    await _show(query, *await _finish_interval(state, window, user.language))


@router.message(ReminderWizard.window)
async def handle_window_text(message: Message, user: User, state: FSMContext) -> None:
    try:
        window = parse_user_window(message.text or "")
    except ValidationError:
        await message.answer(T("wizard.window_invalid", user.language))
        return

    text, keyboard = await _finish_interval(state, window, user.language)
    await message.answer(text, reply_markup=keyboard)


@router.callback_query(
    StateFilter(ReminderWizard), WizCb.filter((F.step == "confirm") & (F.value == "no"))
)
async def handle_cancel(query: CallbackQuery, user: User, state: FSMContext) -> None:
    """Cancelling works on every step, so it is one handler, not nine."""
    await state.clear()
    await query.answer(T("wizard.cancelled", user.language))
    await _show(query, T("wizard.cancelled", user.language), None)


@router.callback_query(
    ReminderWizard.confirm, WizCb.filter((F.step == "confirm") & (F.value == "yes"))
)
async def handle_confirm(
    query: CallbackQuery,
    user: User,
    session: AsyncSession,
    clock: Clock,
    state: FSMContext,
) -> None:
    data = await state.get_data()
    service = RemindersService(session, clock)
    try:
        reminder = await service.create(
            owner_id=user.id,
            category_id=data[CATEGORY_ID_KEY],
            title=data[TITLE_KEY],
            schedule=parse_schedule(data[SCHEDULE_KEY]),
            timezone=user.timezone,
        )
    except ScheduleExhaustedError:
        # Time passed between the confirmation screen and the press.
        await query.answer(T("wizard.past_moment", user.language), show_alert=True)
        return

    # The state goes first: the card is a redraw, and a failing redraw must not
    # leave a finished wizard able to create a second reminder.
    await state.clear()
    category = await CategoriesRepository(session).get_by_id(reminder.category_id)
    await query.answer(T("wizard.created", user.language))
    if category is not None:
        await _show(
            query,
            render_reminder_card(
                reminder,
                category,
                service.next_fire(reminder),
                ZoneInfo(user.timezone),
                user.language,
            ),
            None,
        )


def _preset_time(value: str) -> time | None:
    """A wall-clock atom off a keyboard, or `None` when it is not one.

    A crafted press is the only way to get here with junk, so it is answered
    with silence rather than with a message about a format nobody typed.
    """
    try:
        return parse_hhmm(unpack_wall_time(value))
    except ValueError:
        return None


async def _remember_date(state: FSMContext, day: date) -> None:
    await state.update_data({DATE_KEY: format_local_date(day)})
    await state.set_state(ReminderWizard.at)


async def _ask_window(state: FSMContext, every_minutes: int, lang: Lang) -> Screen:
    await state.update_data({EVERY_MINUTES_KEY: every_minutes})
    await state.set_state(ReminderWizard.window)
    return (T("wizard.ask_window", lang), window_kb(lang))


async def _finish_interval(state: FSMContext, window: tuple[time, time], lang: Lang) -> Screen:
    data = await state.get_data()
    schedule = build_interval_schedule(data[EVERY_MINUTES_KEY], *window)
    return await _to_confirmation(state, schedule, lang)


def _schedule_from(data: dict[str, Any]) -> Schedule:
    """The schedule the collected answers add up to, for the shared times step."""
    times = [parse_hhmm(value) for value in _stored_times(data)]
    kind = ScheduleKind(data[KIND_KEY])
    if kind is ScheduleKind.WEEKLY:
        return build_weekly_schedule(times, _stored_days(data, WEEKDAYS_KEY))
    if kind is ScheduleKind.MONTHLY:
        return build_monthly_schedule(
            times, _stored_days(data, MONTH_DAYS_KEY), data[ON_MISSING_KEY]
        )
    return build_daily_schedule(times)


async def _finish_once(state: FSMContext, at: time, lang: Lang) -> Screen:
    data = await state.get_data()
    schedule = build_once_schedule(parse_local_date(data[DATE_KEY]), at)
    return await _to_confirmation(state, schedule, lang)


async def _to_confirmation(state: FSMContext, schedule: Schedule, lang: Lang) -> Screen:
    """Store the finished payload and ask the one question every kind ends on."""
    data = await state.update_data({SCHEDULE_KEY: dump_schedule(schedule)})
    await state.set_state(ReminderWizard.confirm)
    return (
        render_confirmation(data[TITLE_KEY], schedule, lang),
        confirm_kb("create", 0, lang),
    )


def _times_screen(times: list[str], lang: Lang) -> Screen:
    return (
        T("wizard.ask_times", lang, times=render_times(times, lang)),
        daily_times_kb(times, lang),
    )


def _weekdays_screen(days: list[int], lang: Lang) -> Screen:
    return (
        T("wizard.ask_weekdays", lang, weekdays=render_weekdays(days, lang)),
        weekly_days_kb(days, lang),
    )


def _month_days_screen(days: list[int], lang: Lang) -> Screen:
    return (
        T("wizard.ask_mdays", lang, days=render_month_days(days, lang)),
        monthday_kb(days, lang),
    )


def _stored_times(data: dict[str, Any]) -> list[str]:
    stored = data.get(TIMES_KEY) or []
    return [str(value) for value in stored]


def _stored_days(data: dict[str, Any], key: str) -> list[int]:
    """Day numbers survive a round trip through JSONB, so they come back as ints."""
    stored = data.get(key) or []
    return [int(value) for value in stored]


def _toggle(times: list[str], value: str) -> list[str]:
    """Pressing a chosen time removes it; the list stays sorted and unique."""
    if value in times:
        return [item for item in times if item != value]
    return sorted([*times, value])


def _toggle_day(days: list[int], day: int) -> list[int]:
    """Twin of `_toggle` for day numbers, which sort as numbers, not as text."""
    if day in days:
        return [item for item in days if item != day]
    return sorted([*days, day])


async def _show(query: CallbackQuery, text: str, keyboard: InlineKeyboardMarkup | None) -> None:
    """Redraw the screen in place.

    Pressing a button that changes nothing produces an identical message, and
    Telegram answers that with `message is not modified`. The screen is already
    correct in that case, so the error is the expected outcome, not a failure.
    """
    if not isinstance(query.message, Message):
        return
    try:
        await query.message.edit_text(text, reply_markup=keyboard)
    except TelegramBadRequest as error:
        if "message is not modified" not in str(error):
            raise
