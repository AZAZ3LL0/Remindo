"""The reminder card and everything it opens (tech.md 21.4).

Pause, resume, edit and delete. Creation lives in `handlers/reminders.py`; a
third role in that module would not improve it.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.callbacks import NO_CATEGORY_FILTER, CatCb, EditCb, RemCb, WizCb
from app.bot.fsm.reminder_edit import ReminderEdit
from app.bot.fsm.reminder_wizard import ReminderWizard
from app.bot.handlers.lists import render_list, show
from app.bot.handlers.reminders import CATEGORY_ID_KEY, EDIT_ID_KEY, TITLE_KEY
from app.bot.keyboards.confirm import confirm_kb
from app.bot.keyboards.pickers import category_picker_kb
from app.bot.keyboards.reminders import (
    note_kb,
    reminder_card_kb,
    reminder_edit_kb,
    repeat_picker_kb,
    snooze_picker_kb,
)
from app.bot.keyboards.wizard import schedule_kind_kb
from app.bot.render.reminder import render_reminder_card
from app.bot.render.texts import Lang, T
from app.core.clock import Clock
from app.db.models import Reminder, User
from app.db.repositories.categories import CategoriesRepository
from app.db.repositories.occurrences import OccurrencesRepository
from app.domain.contracts import (
    REPEAT_MAX_MINUTES,
    REPEAT_MIN_MINUTES,
    SNOOZE_MAX_MINUTES,
    SNOOZE_MIN_MINUTES,
    ReminderStatus,
)
from app.domain.errors import ValidationError
from app.domain.reminders import parse_user_repeat, parse_user_snooze
from app.services.categories import CategoriesService
from app.services.reminders import RemindersService

router = Router(name="manage")

#: FSM key holding which reminder the open edit screen belongs to.
REMINDER_ID_KEY = "reminder_id"

Screen = tuple[str, InlineKeyboardMarkup | None]


@router.callback_query(StateFilter(None), RemCb.filter(F.action == "open"))
async def handle_open(
    query: CallbackQuery,
    callback_data: RemCb,
    user: User,
    session: AsyncSession,
    clock: Clock,
) -> None:
    await query.answer()
    await show(query, *await card_screen(user, session, clock, callback_data.reminder_id))


@router.callback_query(StateFilter(None), RemCb.filter(F.action.in_({"pause", "resume"})))
async def handle_pause(
    query: CallbackQuery,
    callback_data: RemCb,
    user: User,
    session: AsyncSession,
    clock: Clock,
) -> None:
    paused = callback_data.action == "pause"
    status = ReminderStatus.PAUSED if paused else ReminderStatus.ACTIVE
    await RemindersService(session, clock).set_status(user.id, callback_data.reminder_id, status)
    await query.answer(T("reminder.paused" if paused else "reminder.resumed", user.language))
    await show(query, *await card_screen(user, session, clock, callback_data.reminder_id))


@router.callback_query(StateFilter(None), RemCb.filter(F.action == "delete"))
async def handle_delete(
    query: CallbackQuery,
    callback_data: RemCb,
    user: User,
    session: AsyncSession,
    clock: Clock,
) -> None:
    reminder = await RemindersService(session, clock).get_owned(user.id, callback_data.reminder_id)
    await query.answer()
    await show(
        query,
        T("reminder.confirm_delete", user.language, title=reminder.title),
        confirm_kb("delete", reminder.id, user.language),
    )


@router.callback_query(StateFilter(None), RemCb.filter(F.action == "confirm_delete"))
async def handle_confirm_delete(
    query: CallbackQuery,
    callback_data: RemCb,
    user: User,
    session: AsyncSession,
    clock: Clock,
) -> None:
    await RemindersService(session, clock).delete(user.id, callback_data.reminder_id)
    await query.answer(T("reminder.deleted", user.language))
    # The list is where the reminder was, and it is the only screen left that
    # still makes sense: the card it was deleted from no longer has a subject.
    await show(query, *await render_list(user, session, clock, 0, NO_CATEGORY_FILTER))


@router.callback_query(StateFilter(None), RemCb.filter(F.action == "edit"))
async def handle_edit(
    query: CallbackQuery,
    callback_data: RemCb,
    user: User,
    session: AsyncSession,
    clock: Clock,
) -> None:
    await RemindersService(session, clock).get_editable(user.id, callback_data.reminder_id)
    await query.answer()
    await show(query, *_edit_menu(callback_data.reminder_id, user.language))


@router.callback_query(StateFilter(None, ReminderEdit), EditCb.filter())
async def handle_edit_field(
    query: CallbackQuery,
    callback_data: EditCb,
    user: User,
    session: AsyncSession,
    clock: Clock,
    state: FSMContext,
) -> None:
    """Open the screen that answers one field (tech.md 21.2)."""
    service = RemindersService(session, clock)
    reminder = await service.get_editable(user.id, callback_data.reminder_id)
    await query.answer()

    if callback_data.field == "menu":
        await state.clear()
        await show(query, *_edit_menu(reminder.id, user.language))
        return

    if callback_data.field == "schedule":
        # The questions are the wizard's, so the wizard asks them. The reminder
        # id in data is what tells its confirmation to update, not to create.
        await state.set_state(ReminderWizard.kind)
        await state.set_data(
            {
                EDIT_ID_KEY: reminder.id,
                TITLE_KEY: reminder.title,
                CATEGORY_ID_KEY: reminder.category_id,
            }
        )
        await show(query, T("edit.pick_kind", user.language), schedule_kind_kb(user.language))
        return

    await state.set_data({REMINDER_ID_KEY: reminder.id})
    await show(query, *await _field_screen(callback_data.field, user, session, clock, state))


@router.message(ReminderEdit.title)
async def handle_title(
    message: Message, user: User, session: AsyncSession, clock: Clock, state: FSMContext
) -> None:
    try:
        await _apply(user, session, clock, state, title=message.text or "")
    except ValidationError:
        await message.answer(T("wizard.title_invalid", user.language))
        return
    await _saved(message, user, session, clock, state)


@router.message(ReminderEdit.note)
async def handle_note(
    message: Message, user: User, session: AsyncSession, clock: Clock, state: FSMContext
) -> None:
    await _apply(user, session, clock, state, note=message.text or "")
    await _saved(message, user, session, clock, state)


@router.callback_query(ReminderEdit.note, WizCb.filter(F.step == "note"))
async def handle_note_clear(
    query: CallbackQuery,
    callback_data: WizCb,
    user: User,
    session: AsyncSession,
    clock: Clock,
    state: FSMContext,
) -> None:
    if callback_data.value != "clear":
        await query.answer()
        return
    await _apply(user, session, clock, state, clear_note=True)
    await query.answer(T("edit.saved", user.language))
    await show(query, *await _back_to_card(user, session, clock, state))


@router.callback_query(ReminderEdit.category, CatCb.filter(F.action == "pick"))
async def handle_category(
    query: CallbackQuery,
    callback_data: CatCb,
    user: User,
    session: AsyncSession,
    clock: Clock,
    state: FSMContext,
) -> None:
    await _apply(user, session, clock, state, category_id=callback_data.category_id)
    await query.answer(T("edit.saved", user.language))
    await show(query, *await _back_to_card(user, session, clock, state))


@router.callback_query(ReminderEdit.snooze, WizCb.filter(F.step == "snooze"))
async def handle_snooze(
    query: CallbackQuery,
    callback_data: WizCb,
    user: User,
    session: AsyncSession,
    clock: Clock,
    state: FSMContext,
) -> None:
    if callback_data.value == "man":
        await query.answer()
        await show(query, T("edit.ask_snooze", user.language), None)
        return
    if not callback_data.value.isdigit():
        await query.answer()
        return

    await _apply(user, session, clock, state, snooze_minutes=int(callback_data.value))
    await query.answer(T("edit.saved", user.language))
    await show(query, *await _back_to_card(user, session, clock, state))


@router.message(ReminderEdit.snooze)
async def handle_snooze_text(
    message: Message, user: User, session: AsyncSession, clock: Clock, state: FSMContext
) -> None:
    try:
        minutes = parse_user_snooze(message.text or "")
    except ValidationError:
        await message.answer(
            T(
                "edit.snooze_invalid",
                user.language,
                minimum=SNOOZE_MIN_MINUTES,
                maximum=SNOOZE_MAX_MINUTES,
            )
        )
        return
    await _apply(user, session, clock, state, snooze_minutes=minutes)
    await _saved(message, user, session, clock, state)


@router.callback_query(ReminderEdit.repeat, WizCb.filter(F.step == "repeat"))
async def handle_repeat(
    query: CallbackQuery,
    callback_data: WizCb,
    user: User,
    session: AsyncSession,
    clock: Clock,
    state: FSMContext,
) -> None:
    if callback_data.value == "man":
        await query.answer()
        await show(query, T("edit.ask_repeat", user.language), None)
        return

    if callback_data.value == "off":
        await _apply(user, session, clock, state, clear_repeat=True)
        await query.answer(T("edit.repeat_off", user.language))
    elif callback_data.value.isdigit():
        await _apply(user, session, clock, state, repeat_after_minutes=int(callback_data.value))
        await query.answer(T("edit.saved", user.language))
    else:
        await query.answer()
        return

    await show(query, *await _back_to_card(user, session, clock, state))


@router.message(ReminderEdit.repeat)
async def handle_repeat_text(
    message: Message, user: User, session: AsyncSession, clock: Clock, state: FSMContext
) -> None:
    try:
        minutes = parse_user_repeat(message.text or "")
    except ValidationError:
        await message.answer(
            T(
                "edit.repeat_invalid",
                user.language,
                minimum=REPEAT_MIN_MINUTES,
                maximum=REPEAT_MAX_MINUTES,
            )
        )
        return
    await _apply(user, session, clock, state, repeat_after_minutes=minutes)
    await _saved(message, user, session, clock, state)


@router.callback_query(
    StateFilter(ReminderEdit), WizCb.filter((F.step == "confirm") & (F.value == "no"))
)
async def handle_cancel(
    query: CallbackQuery,
    user: User,
    session: AsyncSession,
    clock: Clock,
    state: FSMContext,
) -> None:
    """Cancelling works on every edit screen, so it is one handler, not five."""
    screen = await _back_to_card(user, session, clock, state)
    await query.answer(T("edit.cancelled", user.language))
    await show(query, *screen)


async def card_screen(user: User, session: AsyncSession, clock: Clock, reminder_id: int) -> Screen:
    """The card of one reminder, drawn from scratch after every change."""
    service = RemindersService(session, clock)
    reminder = await service.get_owned(user.id, reminder_id)
    category = await CategoriesRepository(session).get_by_id(reminder.category_id)
    if category is None:
        raise LookupError(f"category {reminder.category_id} vanished")

    return (
        render_reminder_card(
            reminder,
            category,
            await _next_fire(reminder, session, clock),
            ZoneInfo(user.timezone),
            user.language,
        ),
        reminder_card_kb(reminder.id, reminder.status, reminder.category_id, user.language),
    )


async def _next_fire(reminder: Reminder, session: AsyncSession, clock: Clock) -> datetime | None:
    """When the card says the reminder fires next.

    A paused reminder has no next moment at all: its queue was taken back
    (tech.md 21.3), and naming one from the schedule would promise a delivery
    that is not coming.
    """
    if reminder.status is not ReminderStatus.ACTIVE:
        return None
    queued = await OccurrencesRepository(session).next_fire_at(reminder.id, clock.now())
    # Falls back to the schedule while the planner has not caught up yet, the
    # same way the card drawn right after creation does (tech.md 18.6).
    return queued or RemindersService(session, clock).next_fire(reminder)


def _edit_menu(reminder_id: int, lang: Lang) -> Screen:
    return T("edit.menu", lang), reminder_edit_kb(reminder_id, lang)


async def _field_screen(
    field: str, user: User, session: AsyncSession, clock: Clock, state: FSMContext
) -> Screen:
    """The question one field asks, and the state it is answered in."""
    if field == "title":
        await state.set_state(ReminderEdit.title)
        return T("edit.ask_title", user.language), None
    if field == "note":
        await state.set_state(ReminderEdit.note)
        return T("edit.ask_note", user.language), note_kb(user.language)
    if field == "category":
        await state.set_state(ReminderEdit.category)
        categories = await CategoriesService(session, clock).list_for_user(user.id)
        return (
            T("edit.ask_category", user.language),
            category_picker_kb(categories, page=0, lang=user.language),
        )
    if field == "snooze":
        await state.set_state(ReminderEdit.snooze)
        return T("edit.ask_snooze", user.language), snooze_picker_kb(user.language)
    await state.set_state(ReminderEdit.repeat)
    return T("edit.ask_repeat", user.language), repeat_picker_kb(user.language)


async def _apply(
    user: User,
    session: AsyncSession,
    clock: Clock,
    state: FSMContext,
    *,
    title: str | None = None,
    note: str | None = None,
    clear_note: bool = False,
    category_id: int | None = None,
    snooze_minutes: int | None = None,
    repeat_after_minutes: int | None = None,
    clear_repeat: bool = False,
) -> None:
    """Write one field of the reminder the open screen belongs to."""
    data = await state.get_data()
    await RemindersService(session, clock).update(
        user.id,
        int(data[REMINDER_ID_KEY]),
        title=title,
        note=note,
        clear_note=clear_note,
        category_id=category_id,
        snooze_minutes=snooze_minutes,
        repeat_after_minutes=repeat_after_minutes,
        clear_repeat=clear_repeat,
    )


async def _back_to_card(
    user: User, session: AsyncSession, clock: Clock, state: FSMContext
) -> Screen:
    data = await state.get_data()
    await state.clear()
    return await card_screen(user, session, clock, int(data[REMINDER_ID_KEY]))


async def _saved(
    message: Message, user: User, session: AsyncSession, clock: Clock, state: FSMContext
) -> None:
    text, keyboard = await _back_to_card(user, session, clock, state)
    await message.answer(T("edit.saved", user.language))
    await message.answer(text, reply_markup=keyboard)
