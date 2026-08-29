"""Validation of a category and derivation of its code.

Pure by contract (tech.md 3, 17.6): no clock, no IO, no imports outside stdlib.
The service is allowed to write a row only because every rule lives here.
"""

import hashlib
import re
import unicodedata
from collections.abc import Collection

from app.domain.contracts import CATEGORY_CODE_PATTERN, CATEGORY_TITLE_MAX_LENGTH
from app.domain.errors import ValidationError

CODE_PATTERN = re.compile(CATEGORY_CODE_PATTERN)
CODE_MIN_LENGTH = 2
CODE_MAX_LENGTH = 32

#: Cyrillic is the common case for this bot and a code has to stay ASCII to
#: satisfy the slug CHECK, so titles are transliterated rather than dropped.
_ONE_LETTER = dict(zip("абвгдеёзийклмнопрстуфхцыэ", "abvgdeeziiklmnoprstufhcye", strict=True))
_MANY_LETTERS = {"ж": "zh", "ч": "ch", "ш": "sh", "щ": "sch", "ю": "yu", "я": "ya"}
_SILENT = {"ъ": "", "ь": ""}
TRANSLITERATION: dict[str, str] = _ONE_LETTER | _MANY_LETTERS | _SILENT

#: Prefix of a code derived from a title that leaves nothing transliterable,
#: for example one written entirely in emoji or in Chinese.
FALLBACK_CODE_PREFIX = "cat_"
FALLBACK_DIGEST_LENGTH = 8

ZWJ = "‍"
KEYCAP = "⃣"
VARIATION_SELECTORS = frozenset({"︎", "️"})
SKIN_TONES = frozenset(chr(point) for point in range(0x1F3FB, 0x1F400))
REGIONAL_INDICATORS = frozenset(chr(point) for point in range(0x1F1E6, 0x1F200))


def normalize_category_title(raw: str) -> str:
    """Trim the edges and collapse inner whitespace, then check the length.

    Normalising before comparison is what makes the uniqueness rule meaningful:
    `Спорт` and `спорт  ` must not become two categories (tech.md 17.6).
    """
    title = " ".join(raw.split())
    if not 1 <= len(title) <= CATEGORY_TITLE_MAX_LENGTH:
        raise ValidationError(f"category title must be 1..{CATEGORY_TITLE_MAX_LENGTH} characters")
    return title


def normalize_emoji(raw: str) -> str:
    """Accept exactly one grapheme cluster (tech.md 4.2, 17.3).

    The rule is about cluster count, not about the character being an emoji:
    deciding what is an emoji needs a Unicode property table the standard
    library does not ship, and guessing one is worse than the column CHECK.
    """
    emoji = raw.strip()
    if not emoji or _cluster_end(emoji, 0) != len(emoji):
        raise ValidationError(f"category emoji must be exactly one grapheme cluster: {raw!r}")
    return emoji


def slugify_code(title: str) -> str:
    """Derive a slug from a title. Same title in, same code out, always.

    The user never types a code, so readability only helps debugging while
    satisfying the slug CHECK is mandatory. A title that leaves nothing usable
    falls back to a digest, which keeps the function total.
    """
    lowered = unicodedata.normalize("NFKD", title).casefold()
    # Combining marks are dropped rather than turned into separators, so that
    # "Учёба" yields `ucheba` instead of `uche_ba`.
    stripped = (char for char in lowered if not unicodedata.combining(char))
    ascii_text = "".join(TRANSLITERATION.get(char, char) for char in stripped)
    slug = re.sub(r"[^a-z0-9]+", "_", ascii_text).strip("_")[:CODE_MAX_LENGTH].strip("_")
    if len(slug) < CODE_MIN_LENGTH:
        return _fallback_code(title)
    return slug


def next_free_code(base: str, taken: Collection[str]) -> str:
    """First free code of the `base`, `base_2`, `base_3`, ... series.

    The base is trimmed instead of the suffix, because a code longer than the
    column allows is rejected by the CHECK while a shortened one is not.
    """
    if base not in taken:
        return base
    for index in range(2, len(taken) + 3):
        suffix = f"_{index}"
        candidate = base[: CODE_MAX_LENGTH - len(suffix)].strip("_") + suffix
        if candidate not in taken:
            return candidate
    raise ValidationError("no free category code left")  # pragma: no cover


def _fallback_code(title: str) -> str:
    """Digest of the title, folded the same way the slug path folds it.

    Hashing the raw string would hand `Спорт` and `спорт  ` two different
    codes while the slug path gives them one, and the rule would stop holding
    exactly where it is least visible.
    """
    folded = " ".join(title.split()).casefold()
    digest = hashlib.blake2s(folded.encode(), digest_size=FALLBACK_DIGEST_LENGTH).hexdigest()
    return f"{FALLBACK_CODE_PREFIX}{digest[:FALLBACK_DIGEST_LENGTH]}"


def _cluster_end(value: str, start: int) -> int:
    """Index right after the grapheme cluster that begins at `start`."""
    if _is_forbidden(value[start]):
        return start
    index = start + 1
    if _is_flag_start(value, start):
        index += 1
    while index < len(value):
        char = value[index]
        if _is_extend(char):
            index += 1
            continue
        if char == ZWJ and index + 1 < len(value) and not _is_forbidden(value[index + 1]):
            index += 2
            continue
        break
    return index


def _is_flag_start(value: str, start: int) -> bool:
    """A flag is a pair of regional indicators and counts as one cluster."""
    return (
        value[start] in REGIONAL_INDICATORS
        and start + 1 < len(value)
        and value[start + 1] in REGIONAL_INDICATORS
    )


def _is_extend(char: str) -> bool:
    return (
        char in VARIATION_SELECTORS
        or char in SKIN_TONES
        or char == KEYCAP
        or unicodedata.category(char) in {"Mn", "Me"}
    )


def _is_forbidden(char: str) -> bool:
    """Whitespace and control characters never belong to a category emoji."""
    if char == ZWJ:
        return False
    return char.isspace() or unicodedata.category(char) in {"Cc", "Cf", "Zs"}
