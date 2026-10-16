"""CommitPolicy (build spec section 7): decides when accumulated
newly-stable ASR text (from TranscriptStabilityFilter) is ready to be sent
to translation as one "committed phrase," rather than translating every
single-word stability update individually.

Deliberately a SEPARATE policy from TranscriptStabilityFilter (spec
sections 7 and 8 are two distinct components): the stability filter's job
is "has this text stopped changing"; this policy's job is "is it now a
good time to act on the text that has stopped changing." A word can be
stable long before it's a good moment to commit (mid-sentence), and the
policy also fires unconditionally at end-of-utterance even if the filter's
own stability criteria were never otherwise met.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum


class CommitTrigger(str, Enum):
    PUNCTUATION = "punctuation"
    SILENCE = "silence"
    STABLE_TOKEN_SEQUENCE = "stable_token_sequence"
    PHRASE_BOUNDARY = "phrase_boundary"
    END_OF_UTTERANCE = "end_of_utterance"
    MAX_DURATION = "max_duration"


@dataclass
class CommitDecision:
    should_commit: bool
    trigger: CommitTrigger | None
    text: str  # the accumulated text to commit; "" when should_commit is False


# Deliberately includes non-Latin sentence terminators the pipeline's
# supported/planned languages actually use (Hindi "।", CJK "。") so this
# isn't silently English/European-punctuation-only.
_SENTENCE_END = (".", "!", "?", "।", "。", "！", "？")
_PHRASE_BOUNDARY = (",", ";", ":", "،")

# A commit fires on stable-token-sequence or phrase-boundary triggers only
# once the buffer holds a real minimum of words — otherwise a single early
# comma or one lucky stable word would fire a near-empty, low-value commit.
_MIN_WORDS_FOR_WEAK_TRIGGER = 3


class CommitPolicy:
    def __init__(
        self,
        max_buffer_ms: float = 2000.0,
        min_stable_revisions: int = 2,
        silence_ms_threshold: float = 500.0,
    ):
        self._max_buffer_ms = max_buffer_ms
        self._min_stable_revisions = min_stable_revisions
        self._silence_ms_threshold = silence_ms_threshold
        self.reset()

    def reset(self) -> None:
        self._buffer_text = ""
        self._buffer_start_time: float | None = None
        self._updates_since_last_commit = 0

    def accept_stable_text(self, newly_stable_text: str, now: float | None = None) -> CommitDecision:
        """Feed one StabilityUpdate.newly_committed_text. Returns a
        no-commit decision if there's nothing new or no trigger fired
        yet."""
        if not newly_stable_text:
            return CommitDecision(should_commit=False, trigger=None, text="")

        now = now if now is not None else time.monotonic()
        if self._buffer_start_time is None:
            self._buffer_start_time = now
        self._buffer_text = (self._buffer_text + " " + newly_stable_text).strip()
        self._updates_since_last_commit += 1

        stripped = self._buffer_text.rstrip()
        word_count = len(self._buffer_text.split())

        if stripped.endswith(_SENTENCE_END):
            return self._commit(CommitTrigger.PUNCTUATION)

        if stripped.endswith(_PHRASE_BOUNDARY) and word_count >= _MIN_WORDS_FOR_WEAK_TRIGGER:
            return self._commit(CommitTrigger.PHRASE_BOUNDARY)

        if self._updates_since_last_commit >= self._min_stable_revisions and word_count >= _MIN_WORDS_FOR_WEAK_TRIGGER:
            return self._commit(CommitTrigger.STABLE_TOKEN_SEQUENCE)

        if (now - self._buffer_start_time) * 1000 >= self._max_buffer_ms:
            return self._commit(CommitTrigger.MAX_DURATION)

        return CommitDecision(should_commit=False, trigger=None, text="")

    def notify_silence(self, silence_ms: float) -> CommitDecision:
        """Turn segmenter reports how long the current silence run has
        been (build spec: "short silence detected")."""
        if self._buffer_text and silence_ms >= self._silence_ms_threshold:
            return self._commit(CommitTrigger.SILENCE)
        return CommitDecision(should_commit=False, trigger=None, text="")

    def notify_end_of_utterance(self) -> CommitDecision:
        """VAD end-of-utterance: commit whatever remains, unconditionally
        — there is no more audio coming for this utterance."""
        if not self._buffer_text:
            return CommitDecision(should_commit=False, trigger=None, text="")
        return self._commit(CommitTrigger.END_OF_UTTERANCE)

    def _commit(self, trigger: CommitTrigger) -> CommitDecision:
        text = self._buffer_text
        self.reset()
        return CommitDecision(should_commit=True, trigger=trigger, text=text)
