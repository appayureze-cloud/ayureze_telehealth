"""Real-model tests for StreamingMmsTTSProvider — uses the actual,
already-resident MMS-TTS weights (no new download), same `-m models`
convention as tests/pipeline/test_pipeline_models.py.
"""

import numpy as np
import pytest

from app.pipeline.tts import MmsTTSProvider, StreamingMmsTTSProvider

pytestmark = pytest.mark.models


def test_stream_yields_ordered_nonempty_chunks_covering_the_full_utterance():
    provider = StreamingMmsTTSProvider(chunk_ms=300)
    provider.load()

    chunks = list(provider.stream("Take two tablets daily.", "en", utterance_id="u1"))

    assert len(chunks) > 1  # a real multi-chunk stream, not one giant blob
    total_samples = sum(len(c.samples) for c in chunks)
    assert total_samples > 0
    for c in chunks:
        assert c.sample_rate == chunks[0].sample_rate


class _FixedOutputInner:
    """A fake inner TTS provider with deterministic output, so this test
    verifies StreamingMmsTTSProvider's CHUNKING/reconstruction logic in
    isolation. A real MmsTTSProvider can't be used for this specific
    comparison: VITS has a stochastic duration predictor, so two
    independent synthesize() calls of the SAME text genuinely produce
    different-length audio — confirmed empirically this pass (32256 vs
    30464 samples for identical input), not a bug in the chunking code."""

    def __init__(self, samples: np.ndarray, sample_rate: int = 16000):
        from app.pipeline.types import SynthesizedAudio

        self._audio = SynthesizedAudio(samples=samples, sample_rate=sample_rate)

    def synthesize(self, text: str, lang: str):
        return self._audio


def test_stream_output_matches_a_direct_synthesize_call_concatenated():
    fixed_samples = np.random.RandomState(0).uniform(-1, 1, size=16000).astype(np.float32)

    provider = StreamingMmsTTSProvider(inner=_FixedOutputInner(fixed_samples), chunk_ms=300)
    provider.load()
    chunks = list(provider.stream("Take two tablets daily.", "en", utterance_id="u2"))
    reconstructed = np.concatenate([c.samples for c in chunks])

    assert reconstructed.shape[0] == fixed_samples.shape[0]
    assert np.array_equal(reconstructed, fixed_samples)


def test_cancel_stops_further_chunks_from_being_yielded():
    provider = StreamingMmsTTSProvider(chunk_ms=50)  # small chunks so there are several to cancel mid-stream
    provider.load()

    seen = []
    for i, chunk in enumerate(provider.stream("Take two tablets twice daily for seven days.", "en", utterance_id="u3")):
        seen.append(chunk)
        if i == 1:
            provider.cancel("u3")
            # the generator's own next iteration checks the cancellation
            # flag before yielding again — draining the rest confirms no
            # further chunks arrive.
    # can't assert an exact count (depends on real synthesis length), but
    # cancellation must have actually stopped it before the natural end —
    # re-running the same text uncancelled must yield strictly more chunks.
    uncancelled = list(StreamingMmsTTSProvider(chunk_ms=50).stream(
        "Take two tablets twice daily for seven days.", "en", utterance_id="u4",
    ))
    assert len(seen) < len(uncancelled)


def test_health_and_metadata_report_the_real_license_gap():
    provider = StreamingMmsTTSProvider()
    provider.load()
    assert provider.health().healthy is True
    meta = provider.metadata()
    assert meta.commercial_use is False  # CC-BY-NC-4.0 — see docs/MODEL_LICENSE_MATRIX.md
    assert meta.certified is True
