"""Shared access contract (tech.md 22): factory, screens and the link.

The seam is `FakeBotGateway.validate_keyboard` and `validate_outgoing`: what
they reject is what Telegram would reject.
"""

import base64
from datetime import UTC, datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from app.bot.callbacks import KNOWN_CALLBACK_FACTORIES, PageCb, ShareCb
from app.bot.keyboards.confirm import confirm_kb
from app.bot.keyboards.pagination import PageItem
from app.bot.keyboards.reminders import reminder_card_kb
from app.bot.keyboards.share import (
    invite_offer_kb,
    share_menu_kb,
    shared_card_kb,
    shared_list_kb,
)
from app.bot.render.reminder import render_reminder_card
from app.bot.render.share import (
    display_name,
    render_share_menu,
    render_shared_card,
    render_shared_list,
)
from app.bot.render.texts import TEXTS, T
from app.domain.contracts import (
    DEEP_LINK_MAX_LENGTH,
    INVITE_TOKEN_BYTES,
    INVITE_TOKEN_LENGTH,
    RecipientRole,
    ReminderStatus,
)
from app.domain.sharing import build_invite_link, build_invite_payload, parse_invite_payload
from app.gateways.bot_gateway import OutgoingMessage
from app.gateways.fakes import MAX_CALLBACK_BYTES, validate_keyboard, validate_outgoing
from app.services.sharing import Participant, SharedReminder

MAX_ID = 2**63 - 1
MOSCOW = ZoneInfo("Europe/Moscow")
MOSCOW_NOON = datetime(2026, 6, 1, 9, 0, tzinfo=UTC)

SHARE_ACTIONS = ("open", "invite", "revoke", "accept", "decline", "leave", "confirm_leave")


def _user(user_id: int = 3, username: str | None = "sam", first_name: str = "Самат"):
    return SimpleNamespace(id=user_id, username=username, first_name=first_name)


def _category(emoji: str = "💧", title: str = "Вода"):
    return SimpleNamespace(id=7, title=title, emoji=emoji)


def _reminder(**overrides):
    fields = {
        "id": MAX_ID,
        "title": "Пить воду",
        "note": None,
        "owner_id": 1,
        "status": ReminderStatus.ACTIVE,
        "category_id": 7,
        "snooze_minutes": 10,
        "repeat_after_minutes": None,
        "schedule": {"kind": "daily", "times": ["08:00", "20:00"], "every_n_days": 1},
    }
    return SimpleNamespace(**{**fields, **overrides})


ITEMS = [
    PageItem(
        text="💧 Пить воду",
        callback_data=ShareCb(reminder_id=MAX_ID, action="open").pack(),
    )
]

#: Every screen the sharing slice can put in front of a user.
KEYBOARDS = {
    "menu_with_link": share_menu_kb(MAX_ID, "ru", has_invite=True),
    "menu_without_link": share_menu_kb(MAX_ID, "ru", has_invite=False),
    "offer": invite_offer_kb(MAX_ID, "ru"),
    "shared_list": shared_list_kb(ITEMS, 1, 3, "ru"),
    "shared_card": shared_card_kb(MAX_ID, "ru"),
    "confirm_leave": confirm_kb("leave", MAX_ID, "ru"),
    "card_with_share": reminder_card_kb(MAX_ID, ReminderStatus.ACTIVE, MAX_ID, "ru"),
}


@pytest.mark.parametrize("keyboard", KEYBOARDS.values(), ids=KEYBOARDS.keys())
def test_keyboard_passes_the_outgoing_contract(keyboard):
    validate_keyboard(keyboard)


@pytest.mark.parametrize("action", SHARE_ACTIONS)
def test_the_factory_survives_the_round_trip_at_full_size(action):
    packed = ShareCb(reminder_id=MAX_ID, action=action).pack()
    assert len(packed.encode()) <= MAX_CALLBACK_BYTES
    unpacked = ShareCb.unpack(packed)
    assert (unpacked.reminder_id, unpacked.action) == (MAX_ID, action)


def test_the_factory_is_registered_with_the_gateway():
    """An unregistered factory makes every screen using it a contract breach."""
    assert ShareCb in KNOWN_CALLBACK_FACTORIES


def test_the_shared_list_pages_without_losing_its_scope():
    keyboard = shared_list_kb(ITEMS, page=1, total_pages=3, lang="ru")
    arrows = [
        PageCb.unpack(button.callback_data)
        for row in keyboard.inline_keyboard
        for button in row
        if button.callback_data and button.callback_data.startswith("p:")
    ]
    assert arrows, "the paginator drew no arrows"
    assert all(arrow.scope == "shared" for arrow in arrows)
    assert {arrow.page for arrow in arrows} == {0, 2}


def test_revoking_is_offered_only_when_there_is_something_to_revoke():
    """A button that changes nothing lies about the state (tech.md 22.7)."""
    with_link = _actions(share_menu_kb(MAX_ID, "ru", has_invite=True))
    without_link = _actions(share_menu_kb(MAX_ID, "ru", has_invite=False))
    assert "revoke" in with_link
    assert "revoke" not in without_link
    assert "invite" in without_link


def test_the_card_is_the_only_door_into_the_access_screen():
    assert "open" in _actions(reminder_card_kb(MAX_ID, ReminderStatus.ACTIVE, MAX_ID, "ru"))


def test_cancelling_a_leave_comes_back_to_the_screen_it_was_asked_on():
    """Unlike creation, unsubscribing has somewhere to return to (tech.md 22.3)."""
    assert _actions(confirm_kb("leave", MAX_ID, "ru")) == {"confirm_leave", "open"}


def _actions(keyboard) -> set[str]:
    return {
        ShareCb.unpack(button.callback_data).action
        for row in keyboard.inline_keyboard
        for button in row
        if button.callback_data and button.callback_data.startswith("i:")
    }


class TestDeepLink:
    def test_the_token_length_matches_the_entropy_it_is_made_of(self):
        """Two numbers stating one fact. Apart, they build a link the parser
        refuses (tech.md 22.4)."""
        encoded = base64.urlsafe_b64encode(b"\x00" * INVITE_TOKEN_BYTES).decode().rstrip("=")
        assert len(encoded) == INVITE_TOKEN_LENGTH

    def test_a_full_size_payload_fits_what_telegram_carries(self):
        assert len(build_invite_payload("a" * INVITE_TOKEN_LENGTH)) <= DEEP_LINK_MAX_LENGTH

    def test_a_link_round_trips_back_into_its_token(self):
        token = "a" * INVITE_TOKEN_LENGTH
        link = build_invite_link("reminder_bot", token)
        assert parse_invite_payload(link.split("?start=")[1]) == token


class TestScreens:
    def test_the_owner_menu_is_a_message_telegram_would_accept(self):
        text = render_share_menu(
            _reminder(),
            [
                Participant(user=_user(1, None, "Хозяин"), role=RecipientRole.OWNER, accepted=True),
                Participant(user=_user(2, "friend"), role=RecipientRole.WATCHER, accepted=True),
                Participant(user=_user(3, None, ""), role=RecipientRole.WATCHER, accepted=False),
            ],
            "ru",
        )
        validate_outgoing(
            OutgoingMessage(
                chat_id=1, text=text, keyboard=share_menu_kb(MAX_ID, "ru", has_invite=True)
            )
        )
        assert "@friend" in text
        assert T("share.pending_mark", "ru") in text

    def test_a_reminder_nobody_shares_says_so_rather_than_showing_an_empty_list(self):
        text = render_share_menu(
            _reminder(),
            [Participant(user=_user(1), role=RecipientRole.OWNER, accepted=True)],
            "ru",
        )
        assert T("share.recipients_none", "ru") in text

    def test_the_watcher_card_names_the_owner_and_the_schedule(self):
        text = render_shared_card(
            _reminder(), _category(), _user(1, "owner"), MOSCOW_NOON, MOSCOW, "ru"
        )
        validate_outgoing(
            OutgoingMessage(chat_id=1, text=text, keyboard=shared_card_kb(MAX_ID, "ru"))
        )
        assert "@owner" in text
        assert "12:00" in text

    def test_a_pending_row_is_marked_in_the_shared_list(self):
        """An unmarked row reads as accepted (tech.md 21.7)."""
        text = render_shared_list(
            [
                (SharedReminder(_reminder(), _user(1, "a"), accepted=True), _category()),
                (SharedReminder(_reminder(id=2), _user(2, "b"), accepted=False), _category()),
            ],
            page=0,
            total=2,
            lang="ru",
        )
        assert text.count(T("share.pending_mark", "ru")) == 1

    def test_an_empty_shared_list_says_so(self):
        assert render_shared_list([], page=0, total=0, lang="ru") == T("share.list_empty", "ru")

    def test_the_owner_card_states_how_many_other_people_get_it(self):
        shared = render_reminder_card(_reminder(), _category(), None, MOSCOW, "ru", watchers=3)
        alone = render_reminder_card(_reminder(), _category(), None, MOSCOW, "ru")
        assert T("reminder.shared", "ru", count=3).strip() in shared
        assert T("reminder.shared", "ru", count=0).strip() not in alone


class TestDisplayName:
    @pytest.mark.parametrize(
        ("user", "expected"),
        [
            (_user(1, "sam", "Самат"), "@sam"),
            (_user(1, None, "Самат"), "Самат"),
            (_user(1, "", "  "), T("share.unknown_user", "ru")),
            (None, T("share.unknown_user", "ru")),
        ],
    )
    def test_a_recipient_always_has_something_to_be_called(self, user, expected):
        """`username` is nullable and `first_name` may be empty (tech.md 4.2)."""
        assert display_name(user, "ru") == expected


def test_every_share_key_ships_in_both_languages():
    """Guarded generally in test_texts, restated here so a missing S10 key
    fails the slice rather than the catalogue."""
    keys = [key for key in TEXTS if key.startswith("share.")]
    assert len(keys) >= 20
    assert all(set(TEXTS[key]) == {"ru", "en"} for key in keys)
