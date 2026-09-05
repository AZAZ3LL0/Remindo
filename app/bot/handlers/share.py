"""Shared reminders: the deep link, the access screen and /shared (tech.md 22).

`/start` has one entry point and it is `handlers/start.py`, so the deep link
arrives here as a function rather than as a second `CommandStart` handler. The
alternative was start and share importing each other.

`/shared` lives here rather than next to `/list` and `/today` (tech.md 21.8):
every row it draws opens a screen from this module, and splitting the two would
tie the list module to this one for the sake of one command.
"""

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.callbacks import PageCb, ShareCb
from app.bot.handlers.lists import PAGE_SIZE, show
from app.bot.keyboards.confirm import confirm_kb
from app.bot.keyboards.pagination import PageItem, page_count
from app.bot.keyboards.share import (
    invite_offer_kb,
    share_menu_kb,
    shared_card_kb,
    shared_list_kb,
)
from app.bot.render.share import (
    display_name,
    render_share_menu,
    render_shared_card,
    render_shared_list,
)
from app.bot.render.texts import T
from app.core.clock import Clock
from app.db.models import Reminder, User
from app.db.repositories.categories import CategoriesRepository
from app.db.repositories.occurrences import OccurrencesRepository
from app.db.repositories.reminders import RemindersRepository
from app.domain.contracts import REMINDER_WATCHERS_MAX, ReminderStatus
from app.domain.errors import (
    InviteExpiredError,
    NotFoundError,
    PermissionDeniedError,
    RecipientLimitError,
    ValidationError,
)
from app.domain.sharing import build_invite_link, parse_invite_payload
from app.services.sharing import SharingService

router = Router(name="share")

Screen = tuple[str, InlineKeyboardMarkup | None]

#: Why a deep link did not let the user in. One reason, one message: "something
#: went wrong" leaves the invitee with nothing to do about it (tech.md 22.5).
_LINK_FAILURES: dict[type[Exception], str] = {
    ValidationError: "share.link_invalid",
    NotFoundError: "share.link_unknown",
    InviteExpiredError: "share.link_dead",
    PermissionDeniedError: "share.own_invite",
}


@dataclass(frozen=True, slots=True)
class DeepLinkResult:
    """What `/start inv_<token>` produced.

    `notice` is said first and `screen` drawn after, so a user who was already
    a recipient is told so and still lands on the reminder. Onboarding decides
    whether the screen is drawn now or after the timezone question, which is
    why the two are handed back separately rather than sent from here.
    """

    notice: str | None = None
    screen: Screen | None = None


async def follow_invite(
    payload: str, user: User, session: AsyncSession, clock: Clock
) -> DeepLinkResult:
    """Resolve a start payload into an invitation (tech.md 22.5).

    Every payload lands here, valid or not: one this bot does not understand is
    still an answer the user deserves, and letting it fall through to the plain
    greeting would swallow a broken invitation in silence.
    """
    service = SharingService(session, clock)
    try:
        reminder, owner = await service.open_invite(parse_invite_payload(payload), user)
    except RecipientLimitError:
        return DeepLinkResult(notice=T("share.full", user.language, maximum=REMINDER_WATCHERS_MAX))
    except tuple(_LINK_FAILURES) as error:
        return DeepLinkResult(notice=T(_LINK_FAILURES[type(error)], user.language))

    _, _, accepted = await service.get_watched(user.id, reminder.id)
    if accepted:
        return DeepLinkResult(
            notice=T("share.already_in", user.language),
            screen=await _watched_screen(user, session, clock, reminder.id),
        )
    return DeepLinkResult(screen=await _offer_screen(user, session, clock, reminder, owner))


async def pending_invite_screen(user: User, session: AsyncSession, clock: Clock) -> Screen | None:
    """The invitation still waiting for an answer, if the user has one.

    Onboarding finishes into it: the invitee met the bot through a link, and
    the question they came for is asked once the timezone is answered.
    """
    service = SharingService(session, clock)
    reminder = await service.pending_invite(user.id)
    if reminder is None:
        return None
    _, owner, _ = await service.get_watched(user.id, reminder.id)
    return await _offer_screen(user, session, clock, reminder, owner)


@router.callback_query(StateFilter(None), ShareCb.filter(F.action == "open"))
async def handle_open(
    query: CallbackQuery,
    callback_data: ShareCb,
    user: User,
    session: AsyncSession,
    clock: Clock,
) -> None:
    """One button, two screens: the owner manages access, a watcher reads it."""
    await query.answer()
    await show(query, *await _access_screen(user, session, clock, callback_data.reminder_id))


@router.callback_query(StateFilter(None), ShareCb.filter(F.action == "invite"))
async def handle_invite(
    query: CallbackQuery,
    callback_data: ShareCb,
    user: User,
    session: AsyncSession,
    clock: Clock,
    bot_username: str,
) -> None:
    invite = await SharingService(session, clock).issue_invite(user.id, callback_data.reminder_id)
    await query.answer()
    # The link goes into a message of its own rather than into the screen: it
    # is meant to be forwarded, and the next redraw would take it away.
    await _reply(
        query,
        T(
            "share.invite_link",
            user.language,
            until=_local(invite.expires_at, user),
            link=build_invite_link(bot_username, invite.token),
        ),
    )
    await show(query, *await _menu_screen(user, session, clock, callback_data.reminder_id))


@router.callback_query(StateFilter(None), ShareCb.filter(F.action == "revoke"))
async def handle_revoke(
    query: CallbackQuery,
    callback_data: ShareCb,
    user: User,
    session: AsyncSession,
    clock: Clock,
) -> None:
    revoked = await SharingService(session, clock).revoke_invite(user.id, callback_data.reminder_id)
    await query.answer(T("share.invite_revoked" if revoked else "share.no_invite", user.language))
    await show(query, *await _menu_screen(user, session, clock, callback_data.reminder_id))


@router.callback_query(StateFilter(None), ShareCb.filter(F.action == "accept"))
async def handle_accept(
    query: CallbackQuery,
    callback_data: ShareCb,
    user: User,
    session: AsyncSession,
    clock: Clock,
) -> None:
    await SharingService(session, clock).accept(user.id, callback_data.reminder_id)
    await query.answer(T("share.accepted", user.language))
    await show(query, *await _watched_screen(user, session, clock, callback_data.reminder_id))


@router.callback_query(StateFilter(None), ShareCb.filter(F.action == "decline"))
async def handle_decline(
    query: CallbackQuery,
    callback_data: ShareCb,
    user: User,
    session: AsyncSession,
    clock: Clock,
) -> None:
    await SharingService(session, clock).decline(user.id, callback_data.reminder_id)
    await query.answer(T("share.declined", user.language))
    await show(query, T("share.declined", user.language), None)


@router.callback_query(StateFilter(None), ShareCb.filter(F.action == "leave"))
async def handle_leave(
    query: CallbackQuery,
    callback_data: ShareCb,
    user: User,
    session: AsyncSession,
    clock: Clock,
) -> None:
    reminder, _, _ = await SharingService(session, clock).get_watched(
        user.id, callback_data.reminder_id
    )
    await query.answer()
    await show(
        query,
        T("share.confirm_leave", user.language, title=reminder.title),
        confirm_kb("leave", reminder.id, user.language),
    )


@router.callback_query(StateFilter(None), ShareCb.filter(F.action == "confirm_leave"))
async def handle_confirm_leave(
    query: CallbackQuery,
    callback_data: ShareCb,
    user: User,
    session: AsyncSession,
    clock: Clock,
) -> None:
    await SharingService(session, clock).leave(user.id, callback_data.reminder_id)
    await query.answer(T("share.left", user.language))
    # The card has lost its subject, so the list is the only screen that still
    # makes sense, the same way it is after a delete (tech.md 21.6).
    await show(query, *await _shared_list(user, session, clock, page=0))


@router.message(Command("shared"))
async def handle_shared(
    message: Message, user: User, session: AsyncSession, clock: Clock, state: FSMContext
) -> None:
    await state.clear()
    text, keyboard = await _shared_list(user, session, clock, page=0)
    await message.answer(text, reply_markup=keyboard)


@router.callback_query(StateFilter(None), PageCb.filter(F.scope == "shared"))
async def handle_shared_page(
    query: CallbackQuery,
    callback_data: PageCb,
    user: User,
    session: AsyncSession,
    clock: Clock,
) -> None:
    await query.answer()
    await show(query, *await _shared_list(user, session, clock, callback_data.page))


async def _access_screen(
    user: User, session: AsyncSession, clock: Clock, reminder_id: int
) -> Screen:
    """Owner or watcher, decided by the recipient row and not by the button."""
    try:
        return await _menu_screen(user, session, clock, reminder_id)
    except PermissionDeniedError:
        return await _watched_screen(user, session, clock, reminder_id)


async def _menu_screen(user: User, session: AsyncSession, clock: Clock, reminder_id: int) -> Screen:
    service = SharingService(session, clock)
    participants = await service.list_participants(user.id, reminder_id)
    reminder = await RemindersRepository(session).get_by_id(reminder_id)
    if reminder is None:
        raise NotFoundError(f"reminder {reminder_id} not found")
    return (
        render_share_menu(reminder, participants, user.language),
        share_menu_kb(
            reminder_id,
            user.language,
            has_invite=await service.live_invite(user.id, reminder_id) is not None,
        ),
    )


async def _watched_screen(
    user: User, session: AsyncSession, clock: Clock, reminder_id: int
) -> Screen:
    reminder, owner, accepted = await SharingService(session, clock).get_watched(
        user.id, reminder_id
    )
    if not accepted:
        return await _offer_screen(user, session, clock, reminder, owner)
    return (
        await _card_text(user, session, clock, reminder, owner),
        shared_card_kb(reminder_id, user.language),
    )


async def _offer_screen(
    user: User, session: AsyncSession, clock: Clock, reminder: Reminder, owner: User
) -> Screen:
    card = await _card_text(user, session, clock, reminder, owner)
    offer = T("share.offer", user.language, owner=display_name(owner, user.language))
    return f"{offer}\n\n{card}", invite_offer_kb(reminder.id, user.language)


async def _card_text(
    user: User, session: AsyncSession, clock: Clock, reminder: Reminder, owner: User
) -> str:
    category = await CategoriesRepository(session).get_by_id(reminder.category_id)
    if category is None:
        raise LookupError(f"category {reminder.category_id} vanished")
    return render_shared_card(
        reminder,
        category,
        owner,
        await _next_fire(reminder, session, clock),
        ZoneInfo(user.timezone),
        user.language,
    )


async def _next_fire(reminder: Reminder, session: AsyncSession, clock: Clock) -> datetime | None:
    """A reminder that is not active has nothing queued, so the watcher is told
    nothing is coming rather than a moment read off a schedule that is not
    running (tech.md 21.3)."""
    if reminder.status is not ReminderStatus.ACTIVE:
        return None
    return await OccurrencesRepository(session).next_fire_at(reminder.id, clock.now())


async def _shared_list(user: User, session: AsyncSession, clock: Clock, page: int) -> Screen:
    items, total = await SharingService(session, clock).list_shared_with(
        user.id, page=page, page_size=PAGE_SIZE
    )
    categories = CategoriesRepository(session)

    rows = []
    buttons = []
    for shared in items:
        category = await categories.get_by_id(shared.reminder.category_id)
        if category is None:
            continue
        rows.append((shared, category))
        buttons.append(
            PageItem(
                text=f"{category.emoji} {shared.reminder.title}",
                callback_data=ShareCb(reminder_id=shared.reminder.id, action="open").pack(),
            )
        )

    return (
        render_shared_list(rows, page=page, total=total, page_size=PAGE_SIZE, lang=user.language),
        shared_list_kb(buttons, page, page_count(total, PAGE_SIZE), user.language),
    )


def _local(moment: datetime, user: User) -> str:
    return moment.astimezone(ZoneInfo(user.timezone)).strftime("%d.%m %H:%M")


async def _reply(query: CallbackQuery, text: str) -> None:
    """Answer next to the pressed button; the screen stays as it was."""
    if isinstance(query.message, Message):
        await query.message.answer(text)
