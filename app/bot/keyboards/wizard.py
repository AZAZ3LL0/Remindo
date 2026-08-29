"""Reminder wizard screens. Handlers never build their own keyboards."""

from collections.abc import Sequence

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.callbacks import WizCb, pack_wall_time
from app.bot.keyboards.pickers import time_picker_kb
from app.bot.render.texts import DEFAULT_LANG, Lang, T
from app.domain.contracts import ScheduleKind

#: `WizCb.value` atoms that are commands rather than data. No time preset may
#: collide with them; the contract test holds that line.
RESERVED_VALUES: frozenset[str] = frozenset({"today", "tmrw", "man", "ok"})

#: Schedule kinds the wizard can build. `interval` stays reachable because the
#: reference slice creates one; `weekly` and `monthly` join the row in S7.
WIZARD_SCHEDULE_KINDS: tuple[ScheduleKind, ...] = (
    ScheduleKind.ONCE,
    ScheduleKind.DAILY,
    ScheduleKind.INTERVAL,
)

#: Wall-clock hours offered for a daily schedule. Anything else arrives as
#: manual input, so the list stays short instead of complete.
DAILY_TIME_PRESETS: tuple[str, ...] = (
    "07:00",
    "08:00",
    "09:00",
    "12:00",
    "15:00",
    "18:00",
    "20:00",
    "22:00",
)

#: Marks a time already in the daily list, so the toggle is visible.
SELECTED_MARK = "• "


def _cancel_button(lang: Lang) -> InlineKeyboardButton:
    """Shared cancel atom (tech.md 17.4). The wizard has no atom of its own."""
    return InlineKeyboardButton(
        text=T("btn.cancel", lang), callback_data=WizCb(step="confirm", value="no").pack()
    )


def _cancel(builder: InlineKeyboardBuilder, lang: Lang) -> None:
    builder.button(text=T("btn.cancel", lang), callback_data=WizCb(step="confirm", value="no"))


def schedule_kind_kb(lang: Lang = DEFAULT_LANG) -> InlineKeyboardMarkup:
    """One button per schedule kind the wizard knows how to build."""
    builder = InlineKeyboardBuilder()
    for kind in WIZARD_SCHEDULE_KINDS:
        builder.button(
            text=T(f"btn.kind_{kind.value}", lang),
            callback_data=WizCb(step="kind", value=kind.value),
        )
    builder.adjust(len(WIZARD_SCHEDULE_KINDS))

    footer = InlineKeyboardBuilder()
    _cancel(footer, lang)
    builder.attach(footer)
    return builder.as_markup()


def date_picker_kb(lang: Lang = DEFAULT_LANG) -> InlineKeyboardMarkup:
    """Today and tomorrow plus manual entry.

    Only two presets, because the keyboard is pure: naming a third day would
    mean reading a clock, and a keyboard never reads one.
    """
    builder = InlineKeyboardBuilder()
    builder.button(text=T("btn.today", lang), callback_data=WizCb(step="date", value="today"))
    builder.button(text=T("btn.tomorrow", lang), callback_data=WizCb(step="date", value="tmrw"))
    builder.button(text=T("btn.manual_input", lang), callback_data=WizCb(step="date", value="man"))
    _cancel(builder, lang)
    builder.adjust(2, 2)
    return builder.as_markup()


def once_time_kb(lang: Lang = DEFAULT_LANG) -> InlineKeyboardMarkup:
    """Shared time presets (tech.md 9) with the wizard's cancel underneath."""
    builder = InlineKeyboardBuilder.from_markup(time_picker_kb("at", lang))
    builder.row(_cancel_button(lang))
    return builder.as_markup()


def daily_times_kb(selected: Sequence[str], lang: Lang = DEFAULT_LANG) -> InlineKeyboardMarkup:
    """Toggles: pressing a chosen time removes it, pressing a free one adds it."""
    chosen = set(selected)
    builder = InlineKeyboardBuilder()
    for value in DAILY_TIME_PRESETS:
        mark = SELECTED_MARK if value in chosen else ""
        builder.button(
            text=f"{mark}{value}",
            callback_data=WizCb(step="time", value=pack_wall_time(value)),
        )
    builder.adjust(4, 4)

    footer = InlineKeyboardBuilder()
    footer.button(text=T("btn.manual_input", lang), callback_data=WizCb(step="time", value="man"))
    footer.button(text=T("btn.ready", lang), callback_data=WizCb(step="times", value="ok"))
    _cancel(footer, lang)
    footer.adjust(2, 1)
    builder.attach(footer)
    return builder.as_markup()
