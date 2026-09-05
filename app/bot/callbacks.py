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

    `shared` pages the reminders somebody else shared with the user. That list
    has no filter, so unlike the reminder list it needs no factory of its own
    (tech.md 22.3).

    `stats` is unused for the same reason `rem` is: the statistics breakdown
    carries a category slice and pages with `StatCb` (tech.md 23.3). It exists
    so that `Scope` and this literal stay one list, and a screen that names its
    scope without overriding the arrows cannot name one that does not exist.
    """

    scope: Literal["rem", "cat", "today", "shared", "stats"]
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


class ShareCb(CallbackData, prefix="i"):
    """Shared access to one reminder (tech.md 22.3).

    It carries the reminder and not the invitation token: by the time any of
    these buttons is pressed the recipient row already exists, so there is no
    reason to put twenty-two characters of token into `callback_data`.
    """

    reminder_id: int
    action: Literal["open", "invite", "revoke", "accept", "decline", "leave", "confirm_leave"]


class StatCb(CallbackData, prefix="t"):
    """Statistics screen: which slice is on it, and which page of the
    breakdown (tech.md 23.3).

    The category rides next to the page for the reason it does in `ListCb`: a
    page that loses the slice on the first arrow lies about what it shows.
    `category_id = 0` is the whole picture, the same `NO_CATEGORY_FILTER` the
    reminder list uses.
    """

    category_id: int
    page: int


class WizCb(CallbackData, prefix="w"):
    step: str  # <= 12 characters
    value: str  # <= 24 characters


class SetCb(CallbackData, prefix="s"):
    """Settings screen. `menu` opens a sub-screen, the rest apply a value.

    `value` carries one atom: a sub-screen name, an IANA zone, a language code
    or a quiet-hours command. It is never a separator-packed pair.
    """

    field: Literal["menu", "tz", "lang", "quiet", "digest"]
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
    ShareCb,
    StatCb,
    WizCb,
    SetCb,
)

#: `ListCb.category_id` and `StatCb.category_id` meaning "every category"
#: (tech.md 21.1, 23.3).
NO_CATEGORY_FILTER = 0

#: Buttons that carry no action, e.g. the page counter in a paginator.
NOOP_CALLBACK = "noop"
