"""Wizard contract (tech.md 18): callback atoms, keyboards, schedule payloads.

The seam is `FakeBotGateway.validate_keyboard`: a keyboard it rejects is a
keyboard Telegram would reject too.
"""

from datetime import date, datetime

import pytest

from app.bot.callbacks import WizCb, pack_wall_time, unpack_wall_time
from app.bot.keyboards.confirm import confirm_kb
from app.bot.keyboards.wizard import (
    DAILY_TIME_PRESETS,
    RESERVED_VALUES,
    SELECTED_MARK,
    WIZARD_SCHEDULE_KINDS,
    daily_times_kb,
    date_picker_kb,
    once_time_kb,
    schedule_kind_kb,
)
from app.domain.contracts import ScheduleKind
from app.domain.schedules import (
    dump_schedule,
    format_local_date,
    parse_local_date,
    parse_schedule,
)
from app.gateways.fakes import MAX_CALLBACK_BYTES, validate_keyboard

#: Longest date the wizard can put in a callback, a year out with a leap day.
LONGEST_DATE = "2028-12-31"

KEYBOARDS = {
    "kind": schedule_kind_kb("ru"),
    "date": date_picker_kb("ru"),
    "once_time": once_time_kb("ru"),
    "daily_times_empty": daily_times_kb([], "ru"),
    "daily_times_all": daily_times_kb(DAILY_TIME_PRESETS, "ru"),
    "confirm_create": confirm_kb("create", 0, "ru"),
}


@pytest.mark.parametrize("keyboard", KEYBOARDS.values(), ids=KEYBOARDS.keys())
def test_keyboard_passes_the_outgoing_contract(keyboard):
    validate_keyboard(keyboard)


WIZARD_ATOMS = [
    ("kind", "once"),
    ("kind", "daily"),
    ("kind", "interval"),
    ("date", "today"),
    ("date", "tmrw"),
    ("date", LONGEST_DATE),
    ("date", "man"),
    ("at", "2359"),
    ("at", "man"),
    ("time", "0730"),
    ("time", "man"),
    ("times", "ok"),
    ("confirm", "yes"),
    ("confirm", "no"),
]


@pytest.mark.parametrize(("step", "value"), WIZARD_ATOMS, ids=lambda part: str(part))
def test_wizard_atom_survives_a_round_trip_inside_the_limit(step, value):
    packed = WizCb(step=step, value=value).pack()

    assert len(packed.encode()) <= MAX_CALLBACK_BYTES
    unpacked = WizCb.unpack(packed)
    assert (unpacked.step, unpacked.value) == (step, value)


@pytest.mark.parametrize("preset", DAILY_TIME_PRESETS)
def test_a_time_preset_travels_packed_and_comes_back_whole(preset):
    """`:` is the callback separator, so the atom drops it and restores it."""
    packed = WizCb(step="time", value=pack_wall_time(preset)).pack()

    assert unpack_wall_time(WizCb.unpack(packed).value) == preset


def test_no_time_preset_collides_with_a_reserved_command():
    """`today`, `tmrw`, `man` and `ok` are commands; no time may shadow one."""
    packed = {pack_wall_time(preset) for preset in DAILY_TIME_PRESETS}

    assert not RESERVED_VALUES.intersection(packed)


def test_time_presets_are_unique():
    assert len(set(DAILY_TIME_PRESETS)) == len(DAILY_TIME_PRESETS)


def test_the_kind_step_offers_exactly_the_kinds_the_wizard_builds():
    """A button for a kind the wizard cannot build is a dead end."""
    assert set(_values(schedule_kind_kb("ru"), "kind")) == {
        kind.value for kind in WIZARD_SCHEDULE_KINDS
    }
    assert set(WIZARD_SCHEDULE_KINDS).issubset(set(ScheduleKind))


def test_every_wizard_screen_can_be_cancelled_by_the_shared_atom():
    """Cancelling is one atom across the product, not one per screen."""
    cancel = WizCb(step="confirm", value="no").pack()

    for keyboard in KEYBOARDS.values():
        assert cancel in _callbacks(keyboard)


def test_the_daily_picker_marks_what_is_already_chosen():
    """The list lives in FSM data, so the keyboard is the only place it shows."""
    chosen = DAILY_TIME_PRESETS[0]
    labels = _labels(daily_times_kb([chosen], "ru"))

    assert f"{SELECTED_MARK}{chosen}" in labels
    assert chosen not in labels


def test_the_daily_picker_keeps_the_same_atoms_whatever_is_chosen():
    """A toggle changes the label, never the callback it sends."""
    assert _callbacks(daily_times_kb([], "ru")) == _callbacks(
        daily_times_kb(DAILY_TIME_PRESETS, "ru")
    )


def test_the_date_atom_needs_no_packing():
    """ISO dates carry no colon, so they travel whole (tech.md 18.1)."""
    day = date(2026, 9, 1)
    packed = WizCb(step="date", value=format_local_date(day)).pack()

    assert parse_local_date(WizCb.unpack(packed).value) == day


@pytest.mark.parametrize(
    "payload",
    [
        {"kind": "once", "at": "2026-09-01T07:30"},
        {"kind": "daily", "times": ["08:00", "20:00"], "every_n_days": 1},
    ],
    ids=["once", "daily"],
)
def test_the_wizard_payload_validates_against_the_schedule_contract(payload):
    """What the wizard writes into JSONB is what tech.md 5 accepts."""
    assert dump_schedule(parse_schedule(payload)) == payload


@pytest.mark.parametrize("raw", ["2026-9-1", "01.09.2026", "20260901", "2026-09-01T07:30", ""])
def test_a_date_outside_the_one_format_is_refused(raw):
    with pytest.raises(ValueError):
        parse_local_date(raw)


def test_a_date_never_smuggles_a_time_along():
    """`datetime` is a `date`; accepting one would drop the time silently."""
    with pytest.raises(ValueError):
        parse_local_date(datetime(2026, 9, 1, 7, 30))


def _callbacks(keyboard) -> set[str]:
    return {
        button.callback_data
        for row in keyboard.inline_keyboard
        for button in row
        if button.callback_data
    }


def _labels(keyboard) -> list[str]:
    return [button.text for row in keyboard.inline_keyboard for button in row]


def _values(keyboard, step: str) -> list[str]:
    values = []
    for data in _callbacks(keyboard):
        try:
            unpacked = WizCb.unpack(data)
        except (TypeError, ValueError):
            continue
        if unpacked.step == step:
            values.append(unpacked.value)
    return values
