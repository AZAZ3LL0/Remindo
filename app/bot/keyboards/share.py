"""Shared access screens (tech.md 22.7).

Handlers never build their own keyboards, so the owner's access menu, the
invitee's offer and the watcher's list and card are assembled here, on top of
the shared primitives of tech.md 9.
"""

from collections.abc import Sequence

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.callbacks import PageCb, RemCb, ShareCb
from app.bot.keyboards.pagination import PageItem, paginated_kb
from app.bot.render.texts import DEFAULT_LANG, Lang, T


def share_menu_kb(
    reminder_id: int, lang: Lang = DEFAULT_LANG, *, has_invite: bool
) -> InlineKeyboardMarkup:
    """The owner's access screen.

    Revoking is drawn only when there is a live link to revoke, by the rule
    that draws one of pause and resume (tech.md 21.6): a button that changes
    nothing lies about the state.
    """
    builder = InlineKeyboardBuilder()
    builder.button(
        text=T("btn.invite", lang), callback_data=ShareCb(reminder_id=reminder_id, action="invite")
    )
    if has_invite:
        builder.button(
            text=T("btn.revoke", lang),
            callback_data=ShareCb(reminder_id=reminder_id, action="revoke"),
        )
    builder.button(
        text=T("btn.back", lang), callback_data=RemCb(reminder_id=reminder_id, action="open")
    )
    builder.adjust(2, 1)
    return builder.as_markup()


def invite_offer_kb(reminder_id: int, lang: Lang = DEFAULT_LANG) -> InlineKeyboardMarkup:
    """What the invitee answers the deep link with (tech.md 22.5)."""
    builder = InlineKeyboardBuilder()
    builder.button(
        text=T("btn.accept", lang), callback_data=ShareCb(reminder_id=reminder_id, action="accept")
    )
    builder.button(
        text=T("btn.decline", lang),
        callback_data=ShareCb(reminder_id=reminder_id, action="decline"),
    )
    builder.adjust(2)
    return builder.as_markup()


def shared_list_kb(
    items: Sequence[PageItem], page: int, total_pages: int, lang: Lang = DEFAULT_LANG
) -> InlineKeyboardMarkup:
    """A page of reminders somebody shared with the user.

    Pages with `PageCb`: the list carries no filter, so unlike the reminder
    list it needs no factory of its own (tech.md 22.3).
    """
    return paginated_kb(items, "shared", page, total_pages, lang)


def shared_card_kb(reminder_id: int, lang: Lang = DEFAULT_LANG) -> InlineKeyboardMarkup:
    """The watcher's card: read it, or stop receiving it (tech.md 22.11)."""
    builder = InlineKeyboardBuilder()
    builder.button(
        text=T("btn.leave", lang), callback_data=ShareCb(reminder_id=reminder_id, action="leave")
    )
    builder.button(text=T("btn.to_shared", lang), callback_data=PageCb(scope="shared", page=0))
    builder.adjust(2)
    return builder.as_markup()
