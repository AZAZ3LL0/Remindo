"""Management contract (tech.md 21): atoms, screens and the card.

The seam is `FakeBotGateway.validate_keyboard`: a keyboard it rejects is a
keyboard Telegram would reject too.
"""

from datetime import UTC, datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from app.bot.callbacks import (
    NO_CATEGORY_FILTER,
    EditCb,
    ListCb,
    PageCb,
    RemCb,
    WizCb,
)
from app.bot.keyboards.confirm import confirm_kb
from app.bot.keyboards.pagination import PageItem
from app.bot.keyboards.reminders import (
    EDIT_FIELDS,
    REPEAT_PRESETS,
    RESERVED_EDIT_VALUES,
    SNOOZE_PRESETS,
    note_kb,
    reminder_card_kb,
    reminder_edit_kb,
    reminder_filter_kb,
    reminder_list_kb,
    repeat_picker_kb,
    snooze_picker_kb,
    today_kb,
)
from app.bot.render.lists import render_reminder_list
from app.bot.render.reminder import render_reminder_card, render_schedule_summary
from app.bot.render.today import render_today
from app.domain.contracts import (
    REPEAT_MAX_MINUTES,
    REPEAT_MIN_MINUTES,
    SNOOZE_MAX_MINUTES,
    SNOOZE_MIN_MINUTES,
    DeliveryStatus,
    ReminderStatus,
)
from app.domain.schedules import parse_schedule
from app.gateways.bot_gateway import OutgoingMessage
from app.gateways.fakes import MAX_CALLBACK_BYTES, validate_keyboard, validate_outgoing
from app.services.today import TodayEntry

MAX_ID = 2**63 - 1

MOSCOW_NOON = datetime(2026, 6, 1, 9, 0, tzinfo=UTC)
MOSCOW = ZoneInfo("Europe/Moscow")


def _category(category_id: int = 7, title: str = "Вода", emoji: str = "💧"):
    return SimpleNamespace(id=category_id, title=title, emoji=emoji)


def _reminder(**overrides):
    fields = {
        "id": 12,
        "title": "Пить воду",
        "note": None,
        "status": ReminderStatus.ACTIVE,
        "category_id": 7,
        "snooze_minutes": 10,
        "repeat_after_minutes": None,
        "schedule": {"kind": "daily", "times": ["08:00", "20:00"], "every_n_days": 1},
    }
    return SimpleNamespace(**{**fields, **overrides})


ITEMS = [PageItem(text="💧 Пить воду", callback_data=RemCb(reminder_id=1, action="open").pack())]

#: Every screen the management slice can put in front of a user.
KEYBOARDS = {
    "list": reminder_list_kb(ITEMS, NO_CATEGORY_FILTER, 0, 3, "ru"),
    "list_filtered": reminder_list_kb(ITEMS, MAX_ID, 1, 3, "ru"),
    "filter": reminder_filter_kb([_category(MAX_ID, "К" * 64)], MAX_ID, "ru"),
    "card_active": reminder_card_kb(MAX_ID, ReminderStatus.ACTIVE, MAX_ID, "ru"),
    "card_paused": reminder_card_kb(MAX_ID, ReminderStatus.PAUSED, NO_CATEGORY_FILTER, "ru"),
    "edit_menu": reminder_edit_kb(MAX_ID, "ru"),
    "snooze": snooze_picker_kb("ru"),
    "repeat": repeat_picker_kb("ru"),
    "note": note_kb("ru"),
    "confirm_delete": confirm_kb("delete", MAX_ID, "ru"),
    "today": today_kb(1, 3, "ru"),
}


@pytest.mark.parametrize("keyboard", KEYBOARDS.values(), ids=KEYBOARDS.keys())
def test_keyboard_passes_the_outgoing_contract(keyboard):
    validate_keyboard(keyboard)


MANAGEMENT_ATOMS = [
    ("snooze", str(SNOOZE_MAX_MINUTES)),
    ("snooze", "man"),
    ("repeat", str(REPEAT_MAX_MINUTES)),
    ("repeat", "off"),
    ("repeat", "man"),
    ("note", "clear"),
    ("filter", str(MAX_ID)),
]


@pytest.mark.parametrize(("step", "value"), MANAGEMENT_ATOMS, ids=lambda part: str(part))
def test_atom_survives_the_round_trip(step, value):
    packed = WizCb(step=step, value=value).pack()
    assert len(packed.encode()) <= MAX_CALLBACK_BYTES
    unpacked = WizCb.unpack(packed)
    assert (unpacked.step, unpacked.value) == (step, value)


def test_presets_never_collide_with_a_command():
    """A preset that reads as `man` or `off` would silently mean something else."""
    presets = {str(minutes) for minutes in (*SNOOZE_PRESETS, *REPEAT_PRESETS)}
    assert not presets & RESERVED_EDIT_VALUES


def test_presets_stay_inside_the_domain_limits():
    """A button the domain would refuse is a button that cannot be pressed."""
    assert all(SNOOZE_MIN_MINUTES <= value <= SNOOZE_MAX_MINUTES for value in SNOOZE_PRESETS)
    assert all(REPEAT_MIN_MINUTES <= value <= REPEAT_MAX_MINUTES for value in REPEAT_PRESETS)


def test_the_list_pages_with_the_filter_it_was_drawn_for():
    """A filter dropped by the first arrow is not a filter (tech.md 21.1)."""
    keyboard = reminder_list_kb(ITEMS, category_id=42, page=1, total_pages=3, lang="ru")
    arrows = [
        ListCb.unpack(button.callback_data)
        for row in keyboard.inline_keyboard
        for button in row
        if button.callback_data and button.callback_data.startswith("l:")
    ]
    assert arrows, "the paginator drew no arrows"
    assert {arrow.category_id for arrow in arrows} == {42}
    assert {arrow.page for arrow in arrows} == {0, 2}


def test_today_pages_without_a_filter():
    """`/today` has no category filter, so it stays on the shared paginator."""
    keyboard = today_kb(page=1, total_pages=3, lang="ru")
    arrows = [
        PageCb.unpack(button.callback_data)
        for row in keyboard.inline_keyboard
        for button in row
        if button.callback_data and button.callback_data.startswith("p:")
    ]
    assert {arrow.scope for arrow in arrows} == {"today"}


@pytest.mark.parametrize("status", [ReminderStatus.ACTIVE, ReminderStatus.PAUSED])
def test_the_card_offers_only_the_button_that_changes_something(status):
    """A button that changes nothing lies about the status (tech.md 21.6)."""
    keyboard = reminder_card_kb(1, status, NO_CATEGORY_FILTER, "ru")
    actions = {
        RemCb.unpack(button.callback_data).action
        for row in keyboard.inline_keyboard
        for button in row
        if button.callback_data and button.callback_data.startswith("m:")
    }
    assert ("pause" in actions) is (status is ReminderStatus.ACTIVE)
    assert ("resume" in actions) is (status is not ReminderStatus.ACTIVE)


def test_cancelling_a_delete_returns_to_the_card():
    """Cancel goes back where it came from, not into nowhere (tech.md 21.6)."""
    keyboard = confirm_kb("delete", 5, "ru")
    actions = [
        RemCb.unpack(button.callback_data).action
        for row in keyboard.inline_keyboard
        for button in row
        if button.callback_data
    ]
    assert actions == ["confirm_delete", "open"]


def test_the_edit_menu_covers_every_editable_field():
    """The menu and the contract list the same fields (tech.md 21.4)."""
    keyboard = reminder_edit_kb(1, "ru")
    fields = [
        EditCb.unpack(button.callback_data).field
        for row in keyboard.inline_keyboard
        for button in row
        if button.callback_data and button.callback_data.startswith("e:")
    ]
    assert fields == list(EDIT_FIELDS)


SCHEDULES = {
    "once": {"kind": "once", "at": "2026-09-01T07:30"},
    "daily": {"kind": "daily", "times": ["08:00"], "every_n_days": 1},
    "weekly": {"kind": "weekly", "times": ["07:30"], "weekdays": [1, 3]},
    "monthly": {
        "kind": "monthly",
        "times": ["10:00"],
        "days": [1, 31],
        "on_missing_day": "last_day",
    },
    "interval": {
        "kind": "interval",
        "every_minutes": 120,
        "window_start": "09:00",
        "window_end": "21:00",
    },
}


@pytest.mark.parametrize("payload", SCHEDULES.values(), ids=SCHEDULES.keys())
@pytest.mark.parametrize("lang", ["ru", "en"])
def test_every_schedule_kind_has_a_card_summary(payload, lang):
    """A kind without a summary would render the card as a traceback."""
    summary = render_schedule_summary(parse_schedule(payload), lang)
    assert summary and "{" not in summary


@pytest.mark.parametrize("lang", ["ru", "en"])
def test_the_card_states_the_schedule_the_note_and_the_repeat(lang):
    card = render_reminder_card(
        _reminder(note="после еды", repeat_after_minutes=30),
        _category(),
        MOSCOW_NOON,
        tz=MOSCOW,
        lang=lang,
    )
    validate_outgoing(OutgoingMessage(chat_id=1, text=card, keyboard=None))
    assert "08:00" in card and "после еды" in card and "30" in card


def test_a_card_without_a_note_says_nothing_about_one():
    card = render_reminder_card(
        _reminder(),
        _category(),
        None,
        tz=MOSCOW,
        lang="ru",
    )
    assert "Заметка" not in card


def test_a_paused_row_is_marked_in_the_list():
    """An unmarked paused row reads as an active one (tech.md 21.7)."""
    rows = [
        (_reminder(id=1, status=ReminderStatus.ACTIVE), _category(), MOSCOW_NOON),
        (_reminder(id=2, status=ReminderStatus.PAUSED), _category(), None),
    ]
    text = render_reminder_list(rows, page=0, total=2, tz=MOSCOW, lang="ru", filter_title="💧 Вода")
    active, paused = text.splitlines()[-2:]
    assert "⏸" in paused and "⏸" not in active
    assert "Фильтр" in text


TODAY_STATUSES = list(DeliveryStatus)


@pytest.mark.parametrize("status", TODAY_STATUSES, ids=lambda value: value.value)
def test_every_delivery_status_has_a_mark_on_the_day(status):
    """A status without a mark would raise while drawing `/today`."""
    entries = [TodayEntry(fire_at=MOSCOW_NOON, emoji="💧", title="Вода", status=status)]
    text = render_today(entries, total=1, tz=MOSCOW, lang="ru")
    validate_outgoing(OutgoingMessage(chat_id=1, text=text, keyboard=None))
    assert "12:00" in text
