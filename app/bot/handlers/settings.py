"""/settings: timezone, language and quiet hours."""

from datetime import time

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.callbacks import SetCb, WizCb, unpack_wall_time
from app.bot.fsm.onboarding import SettingsForm
from app.bot.keyboards.settings import (
    language_picker_kb,
    quiet_menu_kb,
    quiet_time_picker_kb,
    settings_kb,
    timezone_picker_kb,
)
from app.bot.render.settings import format_quiet, render_settings
from app.bot.render.texts import T
from app.core.clock import Clock
from app.db.models import User
from app.domain.errors import ValidationError
from app.domain.onboarding import parse_wall_time
from app.domain.schedules import format_hhmm
from app.services.onboarding import OnboardingService

router = Router(name="settings")

#: FSM key holding the quiet start while the end is still being chosen.
QUIET_START_KEY = "quiet_start"


def _service(
    session: AsyncSession, clock: Clock, default_timezone: str, default_language: str
) -> OnboardingService:
    return OnboardingService(session, clock, default_timezone, default_language)


@router.message(Command("settings"))
async def handle_settings(message: Message, user: User, state: FSMContext) -> None:
    await state.clear()
    await message.answer(render_settings(user), reply_markup=settings_kb(user.language))


@router.callback_query(SetCb.filter(F.field == "menu"))
async def handle_menu(
    query: CallbackQuery, callback_data: SetCb, user: User, state: FSMContext
) -> None:
    """Navigation only. Opening a screen never writes anything."""
    await state.clear()
    lang = user.language
    screen = callback_data.value

    if screen == "root":
        text, keyboard = render_settings(user), settings_kb(lang)
    elif screen == "tz":
        text, keyboard = T("settings.pick_timezone", lang), timezone_picker_kb(lang)
    elif screen == "lang":
        text, keyboard = T("settings.pick_language", lang), language_picker_kb(lang, lang)
    elif screen == "quiet":
        text = T("settings.pick_quiet", lang, quiet=format_quiet(user))
        keyboard = quiet_menu_kb(lang, is_on=user.quiet_start is not None)
    else:
        raise ValidationError(f"unknown settings screen: {screen!r}")

    await query.answer()
    await _show(query, text, keyboard)


@router.callback_query(SetCb.filter(F.field == "tz"))
async def handle_timezone(
    query: CallbackQuery,
    callback_data: SetCb,
    user: User,
    session: AsyncSession,
    clock: Clock,
    state: FSMContext,
    default_timezone: str,
    default_language: str,
) -> None:
    if callback_data.value == "manual":
        await state.set_state(SettingsForm.timezone)
        await query.answer()
        await _show(query, T("start.timezone_manual", user.language), None)
        return

    service = _service(session, clock, default_timezone, default_language)
    updated = await service.set_timezone(user.id, callback_data.value)
    await state.clear()
    await query.answer(T("settings.saved", updated.language))
    await _show(query, render_settings(updated), settings_kb(updated.language))


@router.message(SettingsForm.timezone)
async def handle_timezone_text(
    message: Message,
    user: User,
    session: AsyncSession,
    clock: Clock,
    state: FSMContext,
    default_timezone: str,
    default_language: str,
) -> None:
    service = _service(session, clock, default_timezone, default_language)
    try:
        updated = await service.set_timezone(user.id, message.text or "")
    except ValidationError:
        await message.answer(T("start.timezone_unknown", user.language))
        return

    await state.clear()
    await message.answer(render_settings(updated), reply_markup=settings_kb(updated.language))


@router.callback_query(SetCb.filter(F.field == "lang"))
async def handle_language(
    query: CallbackQuery,
    callback_data: SetCb,
    user: User,
    session: AsyncSession,
    clock: Clock,
    default_timezone: str,
    default_language: str,
) -> None:
    service = _service(session, clock, default_timezone, default_language)
    updated = await service.set_language(user.id, callback_data.value)
    language_name = T(f"lang.{updated.language}", updated.language)
    await query.answer(T("settings.language_saved", updated.language, language=language_name))
    await _show(query, render_settings(updated), settings_kb(updated.language))


@router.callback_query(SetCb.filter(F.field == "quiet"))
async def handle_quiet(
    query: CallbackQuery,
    callback_data: SetCb,
    user: User,
    session: AsyncSession,
    clock: Clock,
    state: FSMContext,
    default_timezone: str,
    default_language: str,
) -> None:
    if callback_data.value == "off":
        service = _service(session, clock, default_timezone, default_language)
        updated = await service.set_quiet_hours(user.id, None, None)
        await state.clear()
        await query.answer(T("settings.quiet_cleared", updated.language))
        await _show(query, render_settings(updated), settings_kb(updated.language))
        return

    await state.set_state(SettingsForm.quiet_start)
    await query.answer()
    await _show(
        query,
        T("settings.pick_quiet_start", user.language),
        quiet_time_picker_kb("qs", user.language),
    )


@router.callback_query(SettingsForm.quiet_start, WizCb.filter(F.step == "qs"))
async def handle_quiet_start(
    query: CallbackQuery, callback_data: WizCb, user: User, state: FSMContext
) -> None:
    if callback_data.value == "man":
        await query.answer()
        await _show(query, T("settings.time_manual", user.language), None)
        return

    await _remember_start(state, parse_wall_time(unpack_wall_time(callback_data.value)))
    await query.answer()
    await _show(
        query,
        T("settings.pick_quiet_end", user.language),
        quiet_time_picker_kb("qe", user.language),
    )


@router.message(SettingsForm.quiet_start)
async def handle_quiet_start_text(message: Message, user: User, state: FSMContext) -> None:
    try:
        start = parse_wall_time(message.text or "")
    except ValidationError:
        await message.answer(T("settings.time_invalid", user.language))
        return

    await _remember_start(state, start)
    await message.answer(
        T("settings.pick_quiet_end", user.language),
        reply_markup=quiet_time_picker_kb("qe", user.language),
    )


@router.callback_query(SettingsForm.quiet_end, WizCb.filter(F.step == "qe"))
async def handle_quiet_end(
    query: CallbackQuery,
    callback_data: WizCb,
    user: User,
    session: AsyncSession,
    clock: Clock,
    state: FSMContext,
    default_timezone: str,
    default_language: str,
) -> None:
    if callback_data.value == "man":
        await query.answer()
        await _show(query, T("settings.time_manual", user.language), None)
        return

    end = parse_wall_time(unpack_wall_time(callback_data.value))
    try:
        updated = await _save_quiet_hours(
            state, session, clock, user, end, default_timezone, default_language
        )
    except ValidationError:
        await query.answer(T("settings.quiet_equal", user.language), show_alert=True)
        return

    await query.answer()
    await _show(query, render_settings(updated), settings_kb(updated.language))


@router.message(SettingsForm.quiet_end)
async def handle_quiet_end_text(
    message: Message,
    user: User,
    session: AsyncSession,
    clock: Clock,
    state: FSMContext,
    default_timezone: str,
    default_language: str,
) -> None:
    try:
        end = parse_wall_time(message.text or "")
    except ValidationError:
        await message.answer(T("settings.time_invalid", user.language))
        return

    try:
        updated = await _save_quiet_hours(
            state, session, clock, user, end, default_timezone, default_language
        )
    except ValidationError:
        await message.answer(T("settings.quiet_equal", user.language))
        return

    await message.answer(render_settings(updated), reply_markup=settings_kb(updated.language))


async def _remember_start(state: FSMContext, start: time) -> None:
    await state.update_data({QUIET_START_KEY: format_hhmm(start)})
    await state.set_state(SettingsForm.quiet_end)


async def _save_quiet_hours(
    state: FSMContext,
    session: AsyncSession,
    clock: Clock,
    user: User,
    end: time,
    default_timezone: str,
    default_language: str,
) -> User:
    """Combine the remembered start with the end and write the interval."""
    data = await state.get_data()
    start = parse_wall_time(data[QUIET_START_KEY])
    service = _service(session, clock, default_timezone, default_language)
    updated = await service.set_quiet_hours(user.id, start, end)
    await state.clear()
    return updated


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
