"""Settings contract (tech.md 16): callback atoms, zones and keyboards.

The seam is `FakeBotGateway.validate_keyboard`: a keyboard it rejects is a
keyboard Telegram would reject too.
"""

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pytest

from app.bot.callbacks import SetCb, pack_wall_time, unpack_wall_time
from app.bot.keyboards.settings import (
    QUIET_HOUR_PRESETS,
    RESERVED_VALUES,
    language_picker_kb,
    quiet_menu_kb,
    quiet_time_picker_kb,
    settings_kb,
    timezone_picker_kb,
)
from app.domain.contracts import POPULAR_TIMEZONES, Language
from app.domain.schedules import parse_hhmm
from app.gateways.fakes import MAX_CALLBACK_BYTES, validate_keyboard

KEYBOARDS = {
    "settings": settings_kb("ru"),
    "timezone": timezone_picker_kb("ru"),
    "timezone_onboarding": timezone_picker_kb("ru", with_back=False),
    "language": language_picker_kb("ru", "ru"),
    "quiet_on": quiet_menu_kb("ru", is_on=True),
    "quiet_off": quiet_menu_kb("ru", is_on=False),
    "quiet_start": quiet_time_picker_kb("qs", "ru"),
    "quiet_end": quiet_time_picker_kb("qe", "ru"),
}


@pytest.mark.parametrize("keyboard", KEYBOARDS.values(), ids=KEYBOARDS.keys())
def test_keyboard_passes_the_outgoing_contract(keyboard):
    validate_keyboard(keyboard)


@pytest.mark.parametrize("zone", POPULAR_TIMEZONES)
def test_popular_zone_is_a_real_iana_name(zone):
    assert ZoneInfo(zone)


@pytest.mark.parametrize("zone", POPULAR_TIMEZONES)
def test_popular_zone_survives_a_round_trip_inside_the_limit(zone):
    packed = SetCb(field="tz", value=zone).pack()

    assert len(packed.encode()) <= MAX_CALLBACK_BYTES
    assert SetCb.unpack(packed).value == zone


def test_popular_zones_are_unique():
    assert len(set(POPULAR_TIMEZONES)) == len(POPULAR_TIMEZONES)


def test_no_data_value_collides_with_a_reserved_command():
    """`manual` and friends are commands; a zone or a language must not shadow one."""
    assert not RESERVED_VALUES.intersection(POPULAR_TIMEZONES)
    assert not RESERVED_VALUES.intersection(code.value for code in Language)


def test_unknown_zone_is_still_carried_verbatim():
    """Manual input reaches the service unmangled, validation happens there."""
    with pytest.raises((ZoneInfoNotFoundError, ValueError)):
        ZoneInfo("Mars/Olympus")


@pytest.mark.parametrize("preset", QUIET_HOUR_PRESETS)
def test_quiet_preset_speaks_the_wall_clock_format(preset):
    assert parse_hhmm(preset)


@pytest.mark.parametrize("preset", QUIET_HOUR_PRESETS)
def test_wall_time_survives_the_callback_atom(preset):
    """`:` is the separator, so a time travels without it and comes back whole."""
    packed = pack_wall_time(preset)

    assert ":" not in packed
    assert unpack_wall_time(packed) == preset
    assert parse_hhmm(unpack_wall_time(packed)) == parse_hhmm(preset)


def test_quiet_presets_cover_both_ends_of_the_night():
    assert "23:00" in QUIET_HOUR_PRESETS
    assert "07:00" in QUIET_HOUR_PRESETS
