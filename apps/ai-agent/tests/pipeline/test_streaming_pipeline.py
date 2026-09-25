"""Async tests for StreamingSessionPipeline, using fake translation/TTS
providers (this repo's own established pattern — see test_tts_gate.py) so
this stays fast and independent of real model weights, while exercising
the REAL CommitPolicy/SafetyCommitPolicy/AudioOutputBuffer/routing logic
underneath.
"""

import asyncio

import numpy as np
import pytest

from app.pipeline.language_registry import Certification, LanguagePairConfig, LanguageRegistry, LicenseStatus
from app.pipeline.model_lifecycle import ModelHealth, ModelMetadata
from app.pipeline.streaming_pipeline import CommittedPhrase, StreamingPipelineConfig, StreamingSessionPipeline
from app.pipeline.translation_router import TranslationRouter
from app.pipeline.tts_router import TTSRouter
from app.pipeline.types import SynthesizedAudio

pytestmark = pytest.mark.asyncio


class FakeTranslationProvider:
    def __init__(self, output_for: dict[str, str] | None = None):
        self._output_for = output_for or {}
        self.calls: list[str] = []

    def health(self) -> ModelHealth:
        return ModelHealth(healthy=True, loaded=True)

    def metadata(self) -> ModelMetadata:
        return ModelMetadata(provider_id="fake-mt", checkpoint="fake", version="1", code_license="Apache-2.0",
                              weights_license="Apache-2.0", commercial_use=True, redistribution=True,
                              attribution_required=False, source_url="", verified_date="2026-09-25")

    def translate(self, text: str, source_lang: str, target_lang: str) -> str:
        self.calls.append(text)
        return self._output_for.get(text, f"[{target_lang}]{text}")


class FakeTTSProvider:
    def __init__(self):
        self.synthesized: list[str] = []
        self.cancelled: set[str] = set()

    def health(self) -> ModelHealth:
        return ModelHealth(healthy=True, loaded=True)

    def metadata(self) -> ModelMetadata:
        return ModelMetadata(provider_id="fake-tts", checkpoint="fake", version="1", code_license="Apache-2.0",
                              weights_license="Apache-2.0", commercial_use=True, redistribution=True,
                              attribution_required=False, source_url="", verified_date="2026-09-25")

    def cancel(self, utterance_id: str) -> None:
        self.cancelled.add(utterance_id)

    def stream(self, text: str, lang: str, utterance_id: str):
        self.synthesized.append(text)
        # 3 small chunks per phrase, so barge-in mid-stream is exercisable.
        for i in range(3):
            if utterance_id in self.cancelled:
                return
            yield SynthesizedAudio(samples=np.array([float(i)], dtype=np.float32), sample_rate=16000)


def _certified_registry():
    reg = LanguageRegistry()
    reg.register(LanguagePairConfig(
        source="en", target="ta",
        translation_primary="mt", translation_fallback=None,
        tts_primary="tts", tts_fallback=None,
        certification=Certification(status="certified", medical_terms=True, dosage=True, negation=True, latency=True),
        license=LicenseStatus(verified=True),
    ))
    return reg


def _make_pipeline(mt: FakeTranslationProvider, tts: FakeTTSProvider, on_audio_chunk=None, on_caption=None, config=None):
    registry = _certified_registry()
    translation_router = TranslationRouter(registry, {"mt": mt})
    tts_router = TTSRouter(registry, {"tts": tts})
    return StreamingSessionPipeline(
        session_id="s1", translation_router=translation_router, tts_router=tts_router,
        config=config, on_audio_chunk=on_audio_chunk, on_caption=on_caption,
    )


async def test_complete_phrase_flows_through_to_audio_and_caption():
    mt = FakeTranslationProvider()
    tts = FakeTTSProvider()
    captions = []
    audio_chunks = []

    async def on_caption(c):
        captions.append(c)

    async def on_audio_chunk(c):
        audio_chunks.append(c)

    pipeline = _make_pipeline(mt, tts, on_audio_chunk=on_audio_chunk, on_caption=on_caption)
    pipeline.begin_utterance("u1")
    await pipeline.start()
    try:
        await pipeline.submit_committed_phrase(
            CommittedPhrase(utterance_id="u1", source_text="Take two tablets daily.", source_lang="en", target_lang="ta")
        )
        await asyncio.wait_for(_drain(pipeline), timeout=2)
    finally:
        await pipeline.stop()

    assert len(captions) == 1
    assert captions[0]["blocked"] is False
    assert captions[0]["translated_text"] is not None
    assert len(audio_chunks) == 3
    assert [c.sequence_number for c in audio_chunks] == [0, 1, 2]


async def test_incomplete_dosage_waits_then_merges_with_next_phrase():
    mt = FakeTranslationProvider()
    tts = FakeTTSProvider()
    captions = []

    async def on_caption(c):
        captions.append(c)

    pipeline = _make_pipeline(mt, tts, on_caption=on_caption)
    pipeline.begin_utterance("u1")
    await pipeline.start()
    try:
        # "Take 5" is the build spec's own incomplete-instruction example.
        await pipeline.submit_committed_phrase(
            CommittedPhrase(utterance_id="u1", source_text="Take 5", source_lang="en", target_lang="ta")
        )
        await asyncio.sleep(0.2)
        assert captions == []  # WAIT_FOR_MORE_CONTEXT — nothing spoken/captioned yet

        await pipeline.submit_committed_phrase(
            CommittedPhrase(utterance_id="u1", source_text="mg twice daily for 7 days.", source_lang="en", target_lang="ta")
        )
        await asyncio.wait_for(_drain(pipeline), timeout=2)
    finally:
        await pipeline.stop()

    assert len(captions) == 1
    # The translator must have been called with the FULL merged source,
    # never just the second fragment alone.
    assert "Take 5 mg twice daily for 7 days." in mt.calls


async def test_barge_in_cancels_in_flight_tts_and_drops_stale_audio():
    mt = FakeTranslationProvider()
    tts = FakeTTSProvider()
    audio_chunks = []

    async def on_audio_chunk(c):
        audio_chunks.append(c)
        if c.utterance_id == "u1":
            # Simulate new speech arriving mid-playback of u1's audio.
            pipeline.begin_utterance("u2")

    pipeline = _make_pipeline(mt, tts, on_audio_chunk=on_audio_chunk)
    pipeline.begin_utterance("u1")
    await pipeline.start()
    try:
        await pipeline.submit_committed_phrase(
            CommittedPhrase(utterance_id="u1", source_text="First sentence.", source_lang="en", target_lang="ta")
        )
        await asyncio.sleep(0.3)
    finally:
        await pipeline.stop()

    # Exactly one chunk of u1's audio played before barge-in cancelled the
    # rest — never all 3.
    u1_chunks = [c for c in audio_chunks if c.utterance_id == "u1"]
    assert 0 < len(u1_chunks) < 3


async def test_blocked_translation_never_reaches_tts():
    # Real Tamil dosage mutation (5 mg -> 50 mg), matching the exact
    # working example from test_safety_commit_policy.py, so the real
    # terminology/safety extraction actually recognizes both sides.
    mt = FakeTranslationProvider(output_for={
        "Take 5 mg twice daily for 7 days.": "தினமும் இருமுறை 7 நாட்களுக்கு 50 மி.கி எடுக்கவும்.",
    })
    tts = FakeTTSProvider()
    captions = []

    async def on_caption(c):
        captions.append(c)

    pipeline = _make_pipeline(mt, tts, on_caption=on_caption)
    pipeline.begin_utterance("u1")
    await pipeline.start()
    try:
        await pipeline.submit_committed_phrase(CommittedPhrase(
            utterance_id="u1", source_text="Take 5 mg twice daily for 7 days.", source_lang="en", target_lang="ta",
        ))
        await asyncio.wait_for(_drain(pipeline), timeout=2)
    finally:
        await pipeline.stop()

    assert len(captions) == 1
    assert captions[0]["blocked"] is True
    assert captions[0]["translated_text"] is None
    assert tts.synthesized == []  # never spoken


async def _drain(pipeline: StreamingSessionPipeline, rounds: int = 20) -> None:
    for _ in range(rounds):
        await asyncio.sleep(0.05)
        if (
            pipeline._translation_queue.empty()
            and pipeline._safety_queue.empty()
            and pipeline._tts_queue.empty()
        ):
            await asyncio.sleep(0.05)
            return
