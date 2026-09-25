"""TranscriptStabilityFilter (build spec section 8): turns a sequence of
growing ASR hypotheses ("I have had", "I have had stomach", "I have had
stomach pain") into the NEWLY stabilized delta at each step, so downstream
consumers (CommitPolicy) never see the same words twice.

Stability rule: a word is considered stable once it survives unchanged as
a prefix from one hypothesis update to the next (word-level longest-common-
prefix between consecutive updates) — matching the build spec's own worked
example exactly. This does not attempt to un-commit already-stable words if
a later, fuller decode contradicts them (a known limitation of streaming
ASR generally; see docs/ai/streaming.md).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class StabilityUpdate:
    newly_committed_text: str  # "" if nothing new stabilized this update
    stable_prefix: str
    unstable_suffix: str
    revision_count: int  # how many times the hypothesis has changed an already-seen word, this utterance


class TranscriptStabilityFilter:
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self._prev_words: list[str] = []
        self._committed_word_count: int = 0
        self._revision_count: int = 0

    def update(self, hypothesis_text: str) -> StabilityUpdate:
        """hypothesis_text is the FULL growing hypothesis so far (not a
        delta) — e.g. from PartialTranscript.text."""
        words = hypothesis_text.split()

        common = 0
        for a, b in zip(self._prev_words, words):
            if a != b:
                break
            common += 1
        if common < len(self._prev_words):
            # The new hypothesis changed something the previous one had
            # already emitted (not merely extended it) — a real ASR
            # revision, not just new speech.
            self._revision_count += 1

        stable_words = words[:common]
        unstable_words = words[common:]

        newly_committed_words = stable_words[self._committed_word_count :]
        self._committed_word_count = max(self._committed_word_count, len(stable_words))
        self._prev_words = words

        return StabilityUpdate(
            newly_committed_text=" ".join(newly_committed_words),
            stable_prefix=" ".join(stable_words),
            unstable_suffix=" ".join(unstable_words),
            revision_count=self._revision_count,
        )

    def finalize(self, final_text: str) -> str:
        """Call on VAD end-of-utterance / STT finalize(). At end of
        utterance there is no more audio to wait for, so everything not
        yet committed becomes committed now, regardless of whether it
        would otherwise still be considered "unstable"."""
        words = final_text.split()
        remaining = words[self._committed_word_count :]
        self._committed_word_count = len(words)
        return " ".join(remaining)
