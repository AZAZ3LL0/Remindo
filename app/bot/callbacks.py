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
    """Generic paginator. `scope` says which list is being paged.

    `rem` is unused since S9: the reminder list carries a category filter and
    pages with `ListCb`. The literal stays because factory values are never
    renamed or dropped, for the same reason enum values are not (tech.md 4.1).
    """

    scope: Literal["rem", "cat", "today"]
    page: int


class ListCb(CallbackData, prefix="l"):
    """Reminder list. Carries the category filter through pagination.

    `PageCb` cannot: a filter lost on the first arrow is not a filter, and
    packing the category into `scope` with a separator is forbidden
    (tech.md 6, 21.1).

    `category_id = 0` means no filter. BIGSERIAL starts at one, so zero can
    never be somebody's row, and a second nullable field is not needed.
    """

    category_id: int
    page: int


class EditCb(CallbackData, prefix="e"):
    """Reminder edit screen: which field is about to change (tech.md 21.2).

    It carries the field and not the value. The value arrives on the next
    screen through `WizCb`, because by then the reminder is in FSM state and
    `value` can stay one atom.
    """

    reminder_id: int
    field: Literal["menu", "title", "note", "category", "schedule", "snooze", "repeat"]


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


def pack_window(start: str, end: str) -> str:
    """A day window as one callback atom, `HHMMHHMM` (tech.md 19.1).

    A window is one answer to one question, and its two ends are never picked
    separately, so it travels as one atom rather than as two steps the way
    quiet hours do (tech.md 16.3).
    """
    return f"{pack_wall_time(start)}{pack_wall_time(end)}"


def unpack_window(value: str) -> tuple[str, str]:
    """Inverse of `pack_window`. Validity is decided by the domain parser."""
    half = len(value) // 2
    return unpack_wall_time(value[:half]), unpack_wall_time(value[half:])


#: Every factory the fake gateway accepts in an outgoing keyboard.
KNOWN_CALLBACK_FACTORIES: tuple[type[CallbackData], ...] = (
    ReactCb,
    RemCb,
    CatCb,
    PageCb,
    ListCb,
    EditCb,
    WizCb,
    SetCb,
)

#: `ListCb.category_id` meaning "every category" (tech.md 21.1).
NO_CATEGORY_FILTER = 0

#: Buttons that carry no action, e.g. the page counter in a paginator.
NOOP_CALLBACK = "noop"
