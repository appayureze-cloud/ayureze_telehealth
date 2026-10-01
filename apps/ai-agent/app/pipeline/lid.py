"""Text-based language identification, used as a cross-check against
faster-whisper's audio-based language detection (stt.py). Two independent
signals — one from the mel-spectrogram, one from the transcribed text —
catch cases where one is wrong (e.g. a short utterance where Whisper's
audio-based guess is unreliable but the transcribed text is unambiguous).
"""

from __future__ import annotations

from abc import ABC, abstractmethod

import langid

from .stt import SUPPORTED_LANGUAGES

langid.set_languages(list(SUPPORTED_LANGUAGES))


class LanguageIDProvider(ABC):
    @abstractmethod
    def identify(self, text: str) -> tuple[str, float]: ...


class LangidProvider(LanguageIDProvider):
    def identify(self, text: str) -> tuple[str, float]:
        if not text.strip():
            return "en", 0.0
        lang, score = langid.classify(text)
        # langid's score is an unnormalized log-likelihood, not a
        # probability; the important direction is 0.0 for empty
        # input.
        return lang, score


def resolve_language(audio_lang: str, audio_confidence: float, text_lang: str) -> str:
    """Combines the STT engine's audio-based guess with the text-based
    LID result. Text-based LID wins on disagreement when the audio-based
    confidence is low — short clinical utterances ("yes", "okay") are
    exactly where audio-based language ID is least reliable.
    """
    if audio_lang == text_lang:
        return audio_lang
    if audio_confidence < 0.6:
        return text_lang
    return audio_lang
