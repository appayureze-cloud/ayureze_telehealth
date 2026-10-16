"""SafetyCommitPolicy (build spec section 12): decides whether a
committed, translated phrase is SAFE_TO_SPEAK, needs to
WAIT_FOR_MORE_CONTEXT, or is BLOCKED outright.

This wraps — never replaces — the existing deterministic safety.validate()
(build spec section H: "KEEP the existing validator... Never replace it
with an LLM"). It adds one new, equally deterministic check ahead of it:
whether the SOURCE phrase itself is clinically complete enough to validate
at all. "Take 5" naming a dosage number with no unit yet is not a
translation-mismatch case safety.validate() is designed to catch — it's an
incomplete instruction that must never reach TTS regardless of what it
translates to (build spec section 11's own "Bad: Take 5 -> TTS" example).

The completeness heuristic below is deterministic and, like the rest of
this build's safety layer, English-only today (see terminology.py's own
documented English/Tamil-only scope) — for any other source language it
is skipped (never guessed), and CommitPolicy's own timing-based commit
triggers remain the only guard against an overly-eager commit in that
case. This is a real, current limitation, not silently glossed over — see
docs/ai/streaming.md.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from . import safety, terminology
from .types import SafetyCheckResult


class SafetyDecision(str, Enum):
    SAFE_TO_SPEAK = "safe_to_speak"
    WAIT_FOR_MORE_CONTEXT = "wait_for_more_context"
    BLOCKED = "blocked"


@dataclass
class SafetyCommitResult:
    decision: SafetyDecision
    safety_check: SafetyCheckResult | None = None  # None for WAIT — the check never ran on an incomplete phrase


# English-only dangling-connective list: a phrase ending in one of these
# grammatically anticipates more words before it can mean anything
# clinically ("for" -> a duration is coming; "twice" -> a duration/timing
# is coming). Deliberately conservative and small — a false "incomplete"
# costs one extra CommitPolicy cycle of buffering; a false "complete"
# risks speaking a truncated dosage instruction.
_DANGLING_TRAILING_WORDS_EN = {
    "for", "with", "before", "after", "at", "every", "and", "or",
    "once", "twice", "thrice", "up", "to", "into", "of",
}


def _strip_trailing_punctuation(text: str) -> str:
    return text.strip().rstrip(".!?,;:")


def _is_number_token(tok: str) -> bool:
    try:
        float(tok)
        return True
    except ValueError:
        return False


def _looks_incomplete_en(text: str) -> bool:
    words = _strip_trailing_punctuation(text).split()
    if not words:
        return True
    last = words[-1].lower()
    if _is_number_token(last):
        return True  # e.g. "Take 5" — a bare number with no unit yet
    if last in _DANGLING_TRAILING_WORDS_EN:
        return True  # e.g. "...twice daily for" — a duration is expected next
    return False


class SafetyCommitPolicy:
    def evaluate(
        self, source_text: str, translated_text: str, source_lang: str = "en", target_lang: str = "en",
    ) -> SafetyCommitResult:
        if not source_text.strip():
            return SafetyCommitResult(decision=SafetyDecision.WAIT_FOR_MORE_CONTEXT, safety_check=None)

        if source_lang == "en" and _looks_incomplete_en(source_text):
            return SafetyCommitResult(decision=SafetyDecision.WAIT_FOR_MORE_CONTEXT, safety_check=None)

        term_analysis = terminology.analyze(source_text)
        result = safety.validate(
            source_text, translated_text, term_analysis, source_lang=source_lang, target_lang=target_lang,
        )
        decision = SafetyDecision.SAFE_TO_SPEAK if result.safe else SafetyDecision.BLOCKED
        return SafetyCommitResult(decision=decision, safety_check=result)
