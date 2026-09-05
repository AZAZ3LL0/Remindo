"""Settings and onboarding keyboards. Handlers never build their own."""

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.callbacks import SetCb, WizCb, pack_wall_time
from app.bot.render.texts import DEFAULT_LANG, Lang, T
from app.domain.contracts import POPULAR_TIMEZONES, Language

#: `SetCb.value` atoms that are commands rather than data. No IANA zone and no
#: language code may collide with them; the contract test holds that line.
RESERVED_VALUES: frozenset[str] = frozenset({"root", "manual", "edit", "off", "on"})

#: Wall-clock hours offered when picking quiet hours. Evening first, morning
#: second, because that is the order the two questions are asked in.
QUIET_HOUR_PRESETS: tuple[str, ...] = (
    "21:00",
    "22:00",
    "23:00",
    "00:00",
    "01:00",
    "05:00",
    "06:00",
    "07:00",
    "08:00",
    "09:00",
)


def _back_button(builder: InlineKeyboardBuilder, lang: Lang) -> None:
    builder.button(text=T("btn.back", lang), callback_data=SetCb(field="menu", value="root"))


def settings_kb(lang: Lang = DEFAULT_LANG, *, digest_on: bool = True) -> InlineKeyboardMarkup:
    """Root settings screen: one button per sub-screen.

    The digest is the exception and toggles in place (tech.md 23.7): the
    question has one answer and two values, and a screen holding a single
    switch would only stand between the question and the answer. The button
    therefore sends the value it would set, never the one already in force,
    by the rule that draws one of pause and resume (tech.md 21.6).
    """
    builder = InlineKeyboardBuilder()
    builder.button(text=T("btn.timezone", lang), callback_data=SetCb(field="menu", value="tz"))
    builder.button(text=T("btn.language", lang), callback_data=SetCb(field="menu", value="lang"))
    builder.button(text=T("btn.quiet", lang), callback_data=SetCb(field="menu", value="quiet"))
    builder.button(
        text=T("btn.digest_off" if digest_on else "btn.digest_on", lang),
        callback_data=SetCb(field="digest", value="off" if digest_on else "on"),
    )
    builder.adjust(2, 2)
    return builder.as_markup()


def timezone_picker_kb(
    lang: Lang = DEFAULT_LANG, *, with_back: bool = True
) -> InlineKeyboardMarkup:
    """Popular zones plus manual IANA entry. Onboarding hides the back button."""
    builder = InlineKeyboardBuilder()
    for zone in POPULAR_TIMEZONES:
        builder.button(text=zone, callback_data=SetCb(field="tz", value=zone))
    builder.adjust(2)

    footer = InlineKeyboardBuilder()
    footer.button(text=T("btn.manual_input", lang), callback_data=SetCb(field="tz", value="manual"))
    if with_back:
        _back_button(footer, lang)
    footer.adjust(2)
    builder.attach(footer)
    return builder.as_markup()


def language_picker_kb(current: str, lang: Lang = DEFAULT_LANG) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for code in Language:
        mark = "• " if code == current else ""
        builder.button(
            text=f"{mark}{T(f'lang.{code.value}', lang)}",
            callback_data=SetCb(field="lang", value=code.value),
        )
    builder.adjust(2)

    footer = InlineKeyboardBuilder()
    _back_button(footer, lang)
    builder.attach(footer)
    return builder.as_markup()


def quiet_menu_kb(lang: Lang = DEFAULT_LANG, *, is_on: bool) -> InlineKeyboardMarkup:
    """Start the two-step picker, or clear the interval when one is set."""
    builder = InlineKeyboardBuilder()
    builder.button(text=T("btn.quiet_set", lang), callback_data=SetCb(field="quiet", value="edit"))
    if is_on:
        builder.button(
            text=T("btn.quiet_off", lang), callback_data=SetCb(field="quiet", value="off")
        )
    _back_button(builder, lang)
    builder.adjust(2, 1)
    return builder.as_markup()


def quiet_time_picker_kb(step: str, lang: Lang = DEFAULT_LANG) -> InlineKeyboardMarkup:
    """One wall-clock hour for `step`, which is the quiet start or the quiet end."""
    builder = InlineKeyboardBuilder()
    for value in QUIET_HOUR_PRESETS:
        builder.button(text=value, callback_data=WizCb(step=step, value=pack_wall_time(value)))
    builder.button(text=T("btn.manual_input", lang), callback_data=WizCb(step=step, value="man"))
    _back_button(builder, lang)
    builder.adjust(5, 5, 2)
    return builder.as_markup()
