"""Categories contract (tech.md 17): callback atoms, emoji presets, keyboards.

The seam is `FakeBotGateway.validate_keyboard`: a keyboard it rejects is a
keyboard Telegram would reject too.
"""

import pytest

from app.bot.callbacks import CatCb, PageCb, WizCb
from app.bot.keyboards.categories import (
    EMOJI_PRESETS,
    RESERVED_VALUES,
    category_card_kb,
    category_list_kb,
    emoji_picker_kb,
)
from app.bot.keyboards.confirm import confirm_kb
from app.bot.keyboards.pickers import CATEGORY_PAGE_SIZE
from app.domain.contracts import CATEGORY_TITLE_MAX_LENGTH
from app.gateways.fakes import MAX_CALLBACK_BYTES, validate_keyboard

#: Ids stay inside BIGSERIAL, and the longest title a category may carry.
MAX_CATEGORY_ID = 2**63 - 1
LONGEST_TITLE = "Ы" * CATEGORY_TITLE_MAX_LENGTH

CAT_ACTIONS = ("pick", "open", "rename", "archive", "confirm_archive")


class FakeCategory:
    """Just the three fields a keyboard reads off a category."""

    def __init__(self, category_id: int, emoji: str, title: str) -> None:
        self.id = category_id
        self.emoji = emoji
        self.title = title


FULL_PAGE = [
    FakeCategory(MAX_CATEGORY_ID - index, EMOJI_PRESETS[index], LONGEST_TITLE)
    for index in range(CATEGORY_PAGE_SIZE)
]

KEYBOARDS = {
    "list_first_page": category_list_kb(FULL_PAGE, 0, 3, "ru"),
    "list_middle_page": category_list_kb(FULL_PAGE, 1, 3, "ru"),
    "list_last_page": category_list_kb(FULL_PAGE, 2, 3, "ru"),
    "list_empty": category_list_kb([], 0, 1, "ru"),
    "card_own": category_card_kb(MAX_CATEGORY_ID, "ru", editable=True),
    "card_system": category_card_kb(MAX_CATEGORY_ID, "ru", editable=False),
    "emoji": emoji_picker_kb("ru"),
    "confirm_archive": confirm_kb("archive", MAX_CATEGORY_ID, "ru"),
}


@pytest.mark.parametrize("keyboard", KEYBOARDS.values(), ids=KEYBOARDS.keys())
def test_keyboard_passes_the_outgoing_contract(keyboard):
    validate_keyboard(keyboard)


@pytest.mark.parametrize("action", CAT_ACTIONS)
def test_category_callback_survives_a_round_trip_inside_the_limit(action):
    packed = CatCb(category_id=MAX_CATEGORY_ID, action=action).pack()

    assert len(packed.encode()) <= MAX_CALLBACK_BYTES
    unpacked = CatCb.unpack(packed)
    assert (unpacked.category_id, unpacked.action) == (MAX_CATEGORY_ID, action)


@pytest.mark.parametrize("emoji", EMOJI_PRESETS)
def test_emoji_preset_survives_the_callback_atom(emoji):
    packed = WizCb(step="emoji", value=emoji).pack()

    assert len(packed.encode()) <= MAX_CALLBACK_BYTES
    assert WizCb.unpack(packed).value == emoji


def test_emoji_presets_are_unique():
    assert len(set(EMOJI_PRESETS)) == len(EMOJI_PRESETS)


def test_no_emoji_preset_collides_with_a_reserved_command():
    """`new`, `cancel` and `man` are commands; an emoji must not shadow one."""
    assert not RESERVED_VALUES.intersection(EMOJI_PRESETS)


def test_the_card_hides_editing_of_a_system_category():
    """A read-only screen must not even offer the buttons the service refuses."""
    system = category_card_kb(1, "ru", editable=False)
    own = category_card_kb(1, "ru", editable=True)

    assert _actions(system) == set()
    assert _actions(own) == {"rename", "archive"}


def test_the_list_offers_creation_on_every_page():
    for page in range(3):
        keyboard = category_list_kb(FULL_PAGE, page, 3, "ru")

        assert WizCb(step="cat", value="new").pack() in _callbacks(keyboard)


def test_the_list_navigates_with_the_shared_page_factory():
    keyboard = category_list_kb(FULL_PAGE, 1, 3, "ru")
    callbacks = _callbacks(keyboard)

    assert PageCb(scope="cat", page=0).pack() in callbacks
    assert PageCb(scope="cat", page=2).pack() in callbacks


def test_an_empty_list_still_lets_the_user_create_the_first_category():
    callbacks = _callbacks(category_list_kb([], 0, 1, "ru"))

    assert WizCb(step="cat", value="new").pack() in callbacks


def _callbacks(keyboard) -> set[str]:
    return {
        button.callback_data
        for row in keyboard.inline_keyboard
        for button in row
        if button.callback_data
    }


def _actions(keyboard) -> set[str]:
    actions = set()
    for data in _callbacks(keyboard):
        try:
            actions.add(CatCb.unpack(data).action)
        except (TypeError, ValueError):
            continue
    return actions
