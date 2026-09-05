"""Reminder list, card and edit screens (tech.md 21.6).

Handlers never build their own keyboards, so every screen the management slice
draws is assembled here, on top of the shared primitives of tech.md 9.
"""

from collections.abc import Sequence

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.callbacks import NO_CATEGORY_FILTER, EditCb, ListCb, RemCb, ShareCb, WizCb
from app.bot.keyboards.pagination import PageItem, paginated_kb
from app.bot.keyboards.pickers import SELECTED_MARK
from app.bot.render.texts import DEFAULT_LANG, Lang, T
from app.db.models import Category
from app.domain.contracts import ReminderStatus

#: Snooze steps offered as buttons, in minutes. Anything else arrives as manual
#: input, so the list stays short instead of complete.
SNOOZE_PRESETS: tuple[int, ...] = (5, 10, 15, 30, 60, 120)

#: Automatic repeat delays offered as buttons, in minutes.
REPEAT_PRESETS: tuple[int, ...] = (15, 30, 60, 120)

#: Fields the edit menu offers, in the order it offers them (tech.md 21.4).
EDIT_FIELDS: tuple[str, ...] = ("title", "note", "category", "schedule", "snooze", "repeat")

#: `WizCb.value` atoms of the edit screens that are commands, not data. No
#: preset may collide with them; the contract test holds that line.
RESERVED_EDIT_VALUES: frozenset[str] = frozenset({"man", "off", "clear"})


def _cancel_button(lang: Lang) -> InlineKeyboardButton:
    """Shared cancel atom (tech.md 17.4). Editing has no atom of its own."""
    return InlineKeyboardButton(
        text=T("btn.cancel", lang), callback_data=WizCb(step="confirm", value="no").pack()
    )


def reminder_list_kb(
    items: Sequence[PageItem],
    category_id: int,
    page: int,
    total_pages: int,
    lang: Lang = DEFAULT_LANG,
) -> InlineKeyboardMarkup:
    """A page of reminders plus the category filter.

    Navigation goes through `ListCb`, so the arrows carry the filter with them
    (tech.md 21.1).
    """
    builder = InlineKeyboardBuilder.from_markup(
        paginated_kb(
            items,
            "rem",
            page,
            total_pages,
            lang,
            nav=lambda target: ListCb(category_id=category_id, page=target),
        )
    )
    # Opening the picker is a command, not a page, so it travels as a `WizCb`
    # atom carrying the filter in force (tech.md 21.2).
    builder.row(
        InlineKeyboardButton(
            text=T("btn.filter", lang),
            callback_data=WizCb(step="filter", value=str(category_id)).pack(),
        )
    )
    return builder.as_markup()


def reminder_filter_kb(
    categories: Sequence[Category], current: int, lang: Lang = DEFAULT_LANG
) -> InlineKeyboardMarkup:
    """Every category the user can filter by, plus the way back to all of them."""
    builder = InlineKeyboardBuilder()
    mark = SELECTED_MARK if current == NO_CATEGORY_FILTER else ""
    builder.button(
        text=f"{mark}{T('btn.all_categories', lang)}",
        callback_data=ListCb(category_id=NO_CATEGORY_FILTER, page=0),
    )
    for category in categories:
        chosen = SELECTED_MARK if category.id == current else ""
        builder.button(
            text=f"{chosen}{category.emoji} {category.title}",
            callback_data=ListCb(category_id=category.id, page=0),
        )
    builder.adjust(1, 2)
    return builder.as_markup()


def reminder_card_kb(
    reminder_id: int,
    status: ReminderStatus,
    category_id: int = NO_CATEGORY_FILTER,
    lang: Lang = DEFAULT_LANG,
) -> InlineKeyboardMarkup:
    """The card of one reminder.

    Exactly one of pause and resume is drawn, the one that changes something:
    the card is where the user reads the status, and a button that changes
    nothing lies about it (tech.md 21.6).
    """
    builder = InlineKeyboardBuilder()
    if status is ReminderStatus.ACTIVE:
        builder.button(
            text=T("btn.pause", lang), callback_data=RemCb(reminder_id=reminder_id, action="pause")
        )
    else:
        builder.button(
            text=T("btn.resume", lang),
            callback_data=RemCb(reminder_id=reminder_id, action="resume"),
        )
    builder.button(
        text=T("btn.edit", lang), callback_data=RemCb(reminder_id=reminder_id, action="edit")
    )
    builder.button(
        text=T("btn.delete", lang), callback_data=RemCb(reminder_id=reminder_id, action="delete")
    )
    # The access screen belongs to this reminder, so the card is the only way
    # in (tech.md 22.7).
    builder.button(
        text=T("btn.share", lang), callback_data=ShareCb(reminder_id=reminder_id, action="open")
    )
    # Back lands in the filtered list the user came from, not in a fresh one.
    builder.button(
        text=T("btn.to_list", lang), callback_data=ListCb(category_id=category_id, page=0)
    )
    builder.adjust(2, 2, 1)
    return builder.as_markup()


def reminder_edit_kb(reminder_id: int, lang: Lang = DEFAULT_LANG) -> InlineKeyboardMarkup:
    """One button per editable field (tech.md 21.4), plus the way back."""
    builder = InlineKeyboardBuilder()
    for field in EDIT_FIELDS:
        builder.button(
            text=T(f"btn.edit_{field}", lang),
            callback_data=EditCb(reminder_id=reminder_id, field=field),
        )
    builder.button(
        text=T("btn.back", lang), callback_data=RemCb(reminder_id=reminder_id, action="open")
    )
    builder.adjust(2, 2, 2, 1)
    return builder.as_markup()


def snooze_picker_kb(lang: Lang = DEFAULT_LANG) -> InlineKeyboardMarkup:
    """Snooze steps in minutes plus manual entry."""
    builder = InlineKeyboardBuilder()
    for minutes in SNOOZE_PRESETS:
        builder.button(text=str(minutes), callback_data=WizCb(step="snooze", value=str(minutes)))
    builder.button(
        text=T("btn.manual_input", lang), callback_data=WizCb(step="snooze", value="man")
    )
    builder.adjust(3, 3, 1)
    builder.row(_cancel_button(lang))
    return builder.as_markup()


def repeat_picker_kb(lang: Lang = DEFAULT_LANG) -> InlineKeyboardMarkup:
    """Repeat delays in minutes, plus turning the repeat off entirely."""
    builder = InlineKeyboardBuilder()
    for minutes in REPEAT_PRESETS:
        builder.button(text=str(minutes), callback_data=WizCb(step="repeat", value=str(minutes)))
    builder.button(text=T("btn.repeat_off", lang), callback_data=WizCb(step="repeat", value="off"))
    builder.button(
        text=T("btn.manual_input", lang), callback_data=WizCb(step="repeat", value="man")
    )
    builder.adjust(4, 2)
    builder.row(_cancel_button(lang))
    return builder.as_markup()


def note_kb(lang: Lang = DEFAULT_LANG) -> InlineKeyboardMarkup:
    """Clearing the note is a button, because an empty message cannot be sent."""
    builder = InlineKeyboardBuilder()
    builder.button(text=T("btn.note_clear", lang), callback_data=WizCb(step="note", value="clear"))
    builder.adjust(1)
    builder.row(_cancel_button(lang))
    return builder.as_markup()


def today_kb(page: int, total_pages: int, lang: Lang = DEFAULT_LANG) -> InlineKeyboardMarkup:
    """Navigation only: the day is a text, and its entries are not buttons.

    Reacting happens on the reminder message the dispatcher sent, which carries
    the delivery its buttons belong to (tech.md 6).
    """
    return paginated_kb((), "today", page, total_pages, lang)
