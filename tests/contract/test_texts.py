"""Text catalogue contract (tech.md 9, 12): every string ships in ru and en."""

import string

import pytest

from app.bot.render.texts import SUPPORTED_LANGS, TEXTS, WEEKDAY_LABELS, T


def placeholders(template: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(template) if name}


@pytest.mark.parametrize("key", sorted(TEXTS))
def test_key_exists_in_every_supported_language(key):
    assert set(TEXTS[key]) == set(SUPPORTED_LANGS)


@pytest.mark.parametrize("key", sorted(TEXTS))
def test_translations_expect_the_same_placeholders(key):
    """A caller passes one set of kwargs, whatever language the user reads in."""
    variants = TEXTS[key]
    expected = placeholders(variants[SUPPORTED_LANGS[0]])

    assert all(placeholders(template) == expected for template in variants.values())


@pytest.mark.parametrize("key", sorted(TEXTS))
def test_no_translation_is_empty(key):
    assert all(template.strip() for template in TEXTS[key].values())


def test_weekday_labels_cover_every_language_and_all_seven_days():
    assert set(WEEKDAY_LABELS) == set(SUPPORTED_LANGS)
    assert all(len(labels) == 7 for labels in WEEKDAY_LABELS.values())


def test_unknown_key_is_a_bug_not_a_silent_fallback():
    with pytest.raises(KeyError):
        T("settings.does_not_exist", "ru")
