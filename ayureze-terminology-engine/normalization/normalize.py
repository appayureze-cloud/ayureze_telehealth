"""Deterministic, non-destructive name normalization (spec section 12).

`normalize_name()` NEVER touches the original value — callers always store
both `name` (verbatim) and `normalized_name` (this function's output)
side by side (see models/concept.py's ConceptName). Normalization is
purely mechanical (Unicode form, whitespace, case, punctuation) and must
NEVER be treated as implying two different names are the same concept —
that is deduplication's job (deduplication/), which requires additional
evidence beyond string equality.
"""

from __future__ import annotations

import re
import unicodedata

_WHITESPACE_RE = re.compile(r"\s+")
# Punctuation normalized away for matching purposes: ASCII punctuation plus
# common Unicode look-alikes (curly quotes, em/en dash) collapsed to
# nothing or a plain space, never to a semantically different character.
_PUNCTUATION_TRANSLATION = str.maketrans(
    {
        # Quote variants (curly and straight alike) map DIRECTLY to empty —
        # str.translate does one lookup per source character, so mapping
        # curly -> straight (a second character that itself maps to empty)
        # would NOT chain into empty; each variant must reach its final
        # form in one step. Verified by a real, previously-failing test:
        # "Doctor’s" and "Doctor's" must normalize identically.
        "‘": "", "’": "", "“": "", "”": "", "'": "", '"': "",
        "–": "-", "—": "-",
        ",": " ", ".": " ", ";": " ", ":": " ", "!": " ", "?": " ",
        "(": " ", ")": " ", "[": " ", "]": " ",
    }
)


def normalize_name(name: str) -> str:
    """Unicode NFKC normalization -> punctuation normalization -> casefold
    -> whitespace collapse -> strip. Deterministic: the same input always
    produces the same output, and this function has no knowledge of any
    concept, source, or language-specific semantics."""
    if not name:
        return ""
    value = unicodedata.normalize("NFKC", name)
    value = value.translate(_PUNCTUATION_TRANSLATION)
    value = value.casefold()
    value = _WHITESPACE_RE.sub(" ", value).strip()
    return value
