"""CallbackData contract (tech.md 6).

Prefixes are frozen forever. A new screen gets a new factory; `value` is never
overloaded with separator-packed strings. Telegram allows 64 bytes per
`callback_data`, and the contract tests hold every factory to that limit.
"""

from typing import Literal

from aiogram.filters.callback_data import CallbackData


class ReactCb(CallbackData, prefix="r"):
    delivery_id: int
    action: Literal["done", "snooze", "skip"]


class RemCb(CallbackData, prefix="m"):
    reminder_id: int
    action: Literal["open", "pause", "resume", "edit", "delete", "confirm_delete"]


class CatCb(CallbackData, prefix="c"):
    """Category screen. Archiving is confirmed: it hides the category from
    every picker, and categories are never hard-deleted because archived
    reminders still point at the row (tech.md 17.1).
    """

    category_id: int
    action: Literal["pick", "open", "rename", "archive", "confirm_archive"]


class PageCb(CallbackData, prefix="p"):
    scope: Literal["rem", "cat", "today"]
    page: int


class WizCb(CallbackData, prefix="w"):
    step: str  # <= 12 characters
    value: str  # <= 24 characters


class SetCb(CallbackData, prefix="s"):
    """Settings screen. `menu` opens a sub-screen, the rest apply a value.

    `value` carries one atom: a sub-screen name, an IANA zone, a language code
    or a quiet-hours command. It is never a separator-packed pair.
    """

    field: Literal["menu", "tz", "lang", "quiet"]
    value: str  # <= 32 characters


def pack_wall_time(value: str) -> str:
    """`HH:MM` as one callback atom.

    `:` is the CallbackData separator and aiogram refuses it inside a value, so
    the colon is dropped rather than the pair being packed with a second one.
    """
    return value.replace(":", "")


def unpack_wall_time(value: str) -> str:
    """Inverse of `pack_wall_time`. Validity is decided by the domain parser."""
    return f"{value[:2]}:{value[2:]}"


#: Every factory the fake gateway accepts in an outgoing keyboard.
KNOWN_CALLBACK_FACTORIES: tuple[type[CallbackData], ...] = (
    ReactCb,
    RemCb,
    CatCb,
    PageCb,
    WizCb,
    SetCb,
)

#: Buttons that carry no action, e.g. the page counter in a paginator.
NOOP_CALLBACK = "noop"
