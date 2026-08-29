"""Category rules (tech.md 17.2, 17.3, 17.6). Pure logic, no database.

The properties come from the acceptance criteria of S2: whatever the user
types, the row that reaches PostgreSQL satisfies the slug CHECK, the emoji
CHECK and the uniqueness rule.
"""

import pytest
from hypothesis import assume, given
from hypothesis import strategies as st

from app.domain.categories import (
    CODE_MAX_LENGTH,
    CODE_MIN_LENGTH,
    CODE_PATTERN,
    next_free_code,
    normalize_category_title,
    normalize_emoji,
    slugify_code,
)
from app.domain.contracts import CATEGORY_TITLE_MAX_LENGTH
from app.domain.errors import ValidationError
from tests.unit.strategies import GRAPHEME_CLUSTERS, category_titles, emoji_clusters

codes = category_titles.map(slugify_code)


class TestTitle:
    @given(category_titles)
    def test_a_normalised_title_fits_the_column(self, title):
        normalized = normalize_category_title(title)

        assert 1 <= len(normalized) <= CATEGORY_TITLE_MAX_LENGTH

    @given(category_titles)
    def test_normalisation_is_idempotent(self, title):
        once = normalize_category_title(title)

        assert normalize_category_title(once) == once

    @given(category_titles)
    def test_a_normalised_title_carries_no_stray_whitespace(self, title):
        normalized = normalize_category_title(title)

        assert normalized == normalized.strip()
        assert "  " not in normalized

    @given(st.text(alphabet=" \t\n", max_size=8))
    def test_a_blank_title_is_refused(self, blank):
        with pytest.raises(ValidationError):
            normalize_category_title(blank)

    @given(st.integers(min_value=CATEGORY_TITLE_MAX_LENGTH + 1, max_value=200))
    def test_an_overlong_title_is_refused(self, length):
        with pytest.raises(ValidationError):
            normalize_category_title("я" * length)

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [("  Спорт ", "Спорт"), ("Уборка   дома", "Уборка дома"), ("A\nB", "A B")],
    )
    def test_known_titles_normalise_the_way_a_user_expects(self, raw, expected):
        assert normalize_category_title(raw) == expected


class TestCode:
    @given(category_titles)
    def test_any_title_yields_a_code_the_check_constraint_accepts(self, title):
        code = slugify_code(normalize_category_title(title))

        assert CODE_PATTERN.match(code)
        assert CODE_MIN_LENGTH <= len(code) <= CODE_MAX_LENGTH

    @given(category_titles)
    def test_the_code_is_deterministic(self, title):
        assert slugify_code(title) == slugify_code(title)

    @given(category_titles)
    def test_titles_that_differ_only_in_spacing_or_case_share_a_code(self, title):
        normalized = normalize_category_title(title)

        assert slugify_code(normalized) == slugify_code(f"  {normalized.upper()}  ")

    @pytest.mark.parametrize(
        ("title", "code"),
        [("Спорт", "sport"), ("Учёба", "ucheba"), ("Yoga 2.0", "yoga_2_0")],
    )
    def test_known_titles_transliterate_the_way_a_reader_expects(self, title, code):
        assert slugify_code(title) == code

    @given(st.text(alphabet="".join(GRAPHEME_CLUSTERS), min_size=1, max_size=8))
    def test_a_title_with_nothing_transliterable_still_yields_a_code(self, title):
        assume(normalize_category_title(title))

        assert CODE_PATTERN.match(slugify_code(title))

    @given(codes, st.integers(min_value=0, max_value=12))
    def test_a_free_code_is_returned_untouched(self, base, size):
        taken = {f"{base}_taken_{index}" for index in range(size)}

        assert next_free_code(base, taken) == base

    @given(codes, st.integers(min_value=1, max_value=12))
    def test_a_taken_code_yields_a_free_one_that_still_fits(self, base, collisions):
        taken = {base} | {f"{base}_{index}" for index in range(2, 2 + collisions)}

        candidate = next_free_code(base, taken)

        assert candidate not in taken
        assert CODE_PATTERN.match(candidate)


class TestEmoji:
    @given(emoji_clusters)
    def test_a_single_cluster_is_accepted_unchanged(self, emoji):
        assert normalize_emoji(emoji) == emoji

    @given(emoji_clusters)
    def test_surrounding_whitespace_is_trimmed(self, emoji):
        assert normalize_emoji(f"  {emoji}\n") == emoji

    @given(emoji_clusters, emoji_clusters)
    def test_two_clusters_are_refused(self, first, second):
        with pytest.raises(ValidationError):
            normalize_emoji(first + second)

    @given(emoji_clusters, emoji_clusters)
    def test_two_clusters_are_refused_even_with_a_space_between_them(self, first, second):
        with pytest.raises(ValidationError):
            normalize_emoji(f"{first} {second}")

    @given(st.text(alphabet=" \t\n", max_size=8))
    def test_a_blank_emoji_is_refused(self, blank):
        with pytest.raises(ValidationError):
            normalize_emoji(blank)

    @given(emoji_clusters)
    def test_normalisation_is_idempotent(self, emoji):
        once = normalize_emoji(emoji)

        assert normalize_emoji(once) == once
