"""Statistics contract (tech.md 23): atoms, screens and the digest message.

The seam is `FakeBotGateway`: a screen it rejects is a screen Telegram would
reject too, and a callback it cannot unpack is one no handler would ever see.
"""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from app.bot.callbacks import NO_CATEGORY_FILTER, NOOP_CALLBACK, PageCb, SetCb, StatCb
from app.bot.keyboards.pagination import PageItem
from app.bot.keyboards.settings import RESERVED_VALUES, settings_kb
from app.bot.keyboards.stats import stats_card_kb, stats_kb
from app.bot.render.stats import render_digest, render_stats, render_stats_card
from app.bot.render.texts import SUPPORTED_LANGS
from app.domain.contracts import POPULAR_TIMEZONES, Language
from app.domain.digest import digest_window, last_digest_moment
from app.domain.stats import CategoryStats, PeriodStats, StatsSummary
from app.gateways.bot_gateway import OutgoingMessage
from app.gateways.fakes import MAX_CALLBACK_BYTES, validate_keyboard, validate_outgoing

MAX_ID = 2**63 - 1
MOSCOW = ZoneInfo("Europe/Moscow")
MONDAY_NINE = datetime(2026, 6, 1, 6, 0, tzinfo=UTC)

CATEGORIES = {
    7: SimpleNamespace(id=7, title="Вода", emoji="💧"),
    9: SimpleNamespace(id=9, title="Таблетки", emoji="💊"),
}


def _period(completed: int = 3, total: int = 4) -> PeriodStats:
    return PeriodStats(completed=completed, total=total)


def _summary(*category_ids: int) -> StatsSummary:
    return StatsSummary(
        current_streak=4,
        longest_streak=9,
        last_7_days=_period(),
        last_30_days=_period(12, 20),
        by_category=tuple(
            CategoryStats(
                category_id=category_id,
                current_streak=2,
                longest_streak=3,
                last_7_days=_period(1, 2),
                last_30_days=_period(5, 9),
            )
            for category_id in category_ids
        ),
    )


def _rows(count: int = 2) -> list[PageItem]:
    return [
        PageItem(text=f"💧 {index}", callback_data=StatCb(category_id=index, page=0).pack())
        for index in range(1, count + 1)
    ]


SCREENS = {
    "breakdown": stats_kb(_rows(), page=0, total_pages=3, lang="ru"),
    "breakdown_last_page": stats_kb(_rows(), page=2, total_pages=3, lang="ru"),
    "card": stats_card_kb("ru"),
    "settings_digest_on": settings_kb("ru", digest_on=True),
    "settings_digest_off": settings_kb("ru", digest_on=False),
}


@pytest.mark.parametrize("keyboard", SCREENS.values(), ids=list(SCREENS))
def test_every_screen_passes_the_gateway_contract(keyboard):
    validate_keyboard(keyboard)


def _callbacks(keyboard) -> list[str]:
    return [
        button.callback_data
        for row in keyboard.inline_keyboard
        for button in row
        if button.callback_data
    ]


def _nav(keyboard) -> list[StatCb]:
    """The arrows of a paginated screen: its last row, counter aside."""
    return [
        StatCb.unpack(button.callback_data)
        for button in keyboard.inline_keyboard[-1]
        if button.callback_data and button.callback_data != NOOP_CALLBACK
    ]


def test_the_breakdown_pages_with_its_own_factory():
    """Arrows carry `StatCb`, not `PageCb`, and they stay on the whole picture:
    a page that loses its slice is not a slice (tech.md 23.3)."""
    data = _callbacks(SCREENS["breakdown"])
    assert not any(item.startswith(f"{PageCb.__prefix__}:") for item in data)
    assert _nav(SCREENS["breakdown"]) == [StatCb(category_id=NO_CATEGORY_FILTER, page=1)]


def test_a_breakdown_row_opens_that_category():
    rows = _rows(2)
    assert [StatCb.unpack(row.callback_data).category_id for row in rows] == [1, 2]


def test_the_card_returns_to_every_category():
    data = _callbacks(SCREENS["card"])
    assert [StatCb.unpack(item) for item in data] == [
        StatCb(category_id=NO_CATEGORY_FILTER, page=0)
    ]


def test_the_last_page_hides_the_forward_arrow():
    assert _nav(SCREENS["breakdown_last_page"]) == [StatCb(category_id=NO_CATEGORY_FILTER, page=1)]


def test_a_maximal_stat_callback_fits_the_limit():
    packed = StatCb(category_id=MAX_ID, page=999_999).pack()
    assert len(packed.encode()) <= MAX_CALLBACK_BYTES
    assert StatCb.unpack(packed) == StatCb(category_id=MAX_ID, page=999_999)


def test_the_digest_switch_offers_the_side_it_would_set():
    """A button that changes nothing lies about the state (tech.md 21.6)."""
    on = [SetCb.unpack(d) for d in _callbacks(SCREENS["settings_digest_on"]) if d.startswith("s:")]
    off = [
        SetCb.unpack(d) for d in _callbacks(SCREENS["settings_digest_off"]) if d.startswith("s:")
    ]

    assert SetCb(field="digest", value="off") in on
    assert SetCb(field="digest", value="on") in off
    assert SetCb(field="digest", value="on") not in on


def test_digest_atoms_collide_with_nothing_offered_as_data():
    """`on` and `off` are commands, so no zone or language may look like one."""
    assert {"on", "off"} <= RESERVED_VALUES
    assert not RESERVED_VALUES & set(POPULAR_TIMEZONES)
    assert not RESERVED_VALUES & {language.value for language in Language}


@pytest.mark.parametrize("lang", SUPPORTED_LANGS)
def test_the_whole_picture_is_a_sendable_message(lang):
    text = render_stats(_summary(7, 9), CATEGORIES, lang)
    validate_outgoing(OutgoingMessage(chat_id=1, text=text, keyboard=stats_kb(_rows(), 0, 1, lang)))
    assert "Вода" in text and "Таблетки" in text


@pytest.mark.parametrize("lang", SUPPORTED_LANGS)
def test_a_history_without_outcomes_says_so_instead_of_showing_nothing(lang):
    text = render_stats(_summary(), {}, lang)
    validate_outgoing(OutgoingMessage(chat_id=1, text=text, keyboard=stats_kb([], 0, 1, lang)))


def test_a_deleted_category_is_left_out_rather_than_rendered_blank():
    """The breakdown names a row through the category, so a missing one has no
    label and no card to open."""
    text = render_stats(_summary(7, 9), {7: CATEGORIES[7]}, "ru")
    assert "Вода" in text and "Таблетки" not in text


@pytest.mark.parametrize("lang", SUPPORTED_LANGS)
def test_a_category_card_is_a_sendable_message(lang):
    text = render_stats_card(_summary(), CATEGORIES[7], lang)
    validate_outgoing(OutgoingMessage(chat_id=1, text=text, keyboard=stats_card_kb(lang)))


@pytest.mark.parametrize("lang", SUPPORTED_LANGS)
def test_the_digest_is_a_sendable_message_without_buttons(lang):
    """It answers nothing, so it carries no keyboard (tech.md 23.5)."""
    window = digest_window(MONDAY_NINE, MOSCOW)
    text = render_digest(_summary(7, 9), window, CATEGORIES, MOSCOW, lang)
    validate_outgoing(OutgoingMessage(chat_id=1, text=text, keyboard=None))


def test_the_digest_names_the_week_it_covers():
    window = digest_window(MONDAY_NINE, MOSCOW)
    text = render_digest(_summary(7), window, CATEGORIES, MOSCOW, "ru")
    assert "2026-05-25" in text and "2026-06-01" in text


def test_the_digest_window_ends_at_the_moment_it_is_keyed_on():
    """The title and the idempotency key describe the same week."""
    moment = last_digest_moment(MONDAY_NINE + timedelta(days=3), MOSCOW, 1, 9)
    assert digest_window(moment, MOSCOW).end == moment == MONDAY_NINE
