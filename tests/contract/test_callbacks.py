"""CallbackData contract (tech.md 6): round-trip and the 64-byte limit."""

import pytest

from app.bot.callbacks import (
    KNOWN_CALLBACK_FACTORIES,
    NO_CATEGORY_FILTER,
    CatCb,
    EditCb,
    ListCb,
    PageCb,
    ReactCb,
    RemCb,
    SetCb,
    ShareCb,
    StatCb,
    WizCb,
)

MAX_CALLBACK_BYTES = 64

#: Largest values each factory can carry in production.
MAXIMAL = [
    ReactCb(delivery_id=2**63 - 1, action="snooze"),
    RemCb(reminder_id=2**63 - 1, action="confirm_delete"),
    CatCb(category_id=2**63 - 1, action="archive"),
    PageCb(scope="today", page=999_999),
    ListCb(category_id=2**63 - 1, page=999_999),
    EditCb(reminder_id=2**63 - 1, field="schedule"),
    ShareCb(reminder_id=2**63 - 1, action="confirm_leave"),
    StatCb(category_id=2**63 - 1, page=999_999),
    WizCb(step="x" * 12, value="y" * 24),
    SetCb(field="digest", value="z" * 32),
]


@pytest.mark.parametrize("callback", MAXIMAL, ids=lambda cb: type(cb).__name__)
def test_packed_callback_fits_telegram_limit(callback):
    assert len(callback.pack().encode()) <= MAX_CALLBACK_BYTES


@pytest.mark.parametrize("callback", MAXIMAL, ids=lambda cb: type(cb).__name__)
def test_pack_unpack_round_trip(callback):
    assert type(callback).unpack(callback.pack()) == callback


def test_prefixes_are_frozen():
    """Prefixes are part of the wire format and never change."""
    assert [factory.__prefix__ for factory in KNOWN_CALLBACK_FACTORIES] == [
        "r",
        "m",
        "c",
        "p",
        "l",
        "e",
        "i",
        "t",
        "w",
        "s",
    ]


def test_prefixes_are_unique():
    prefixes = [factory.__prefix__ for factory in KNOWN_CALLBACK_FACTORIES]
    assert len(set(prefixes)) == len(prefixes)


def test_no_filter_can_never_be_a_real_category():
    """`0` means "every category" because BIGSERIAL never hands it out."""
    assert NO_CATEGORY_FILTER == 0
    assert ListCb.unpack(ListCb(category_id=NO_CATEGORY_FILTER, page=0).pack()).category_id == 0


def test_reaction_targets_a_delivery_not_an_occurrence():
    """A reaction always belongs to one recipient, so it carries delivery_id."""
    assert "delivery_id" in ReactCb.model_fields
    assert "occurrence_id" not in ReactCb.model_fields
