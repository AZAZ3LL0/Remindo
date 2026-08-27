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
    category_id: int
    action: Literal["pick", "open", "rename", "archive"]


class PageCb(CallbackData, prefix="p"):
    scope: Literal["rem", "cat", "today"]
    page: int


class WizCb(CallbackData, prefix="w"):
    step: str  # <= 12 characters
    value: str  # <= 24 characters


#: Every factory the fake gateway accepts in an outgoing keyboard.
KNOWN_CALLBACK_FACTORIES: tuple[type[CallbackData], ...] = (
    ReactCb,
    RemCb,
    CatCb,
    PageCb,
    WizCb,
)

#: Buttons that carry no action, e.g. the page counter in a paginator.
NOOP_CALLBACK = "noop"
