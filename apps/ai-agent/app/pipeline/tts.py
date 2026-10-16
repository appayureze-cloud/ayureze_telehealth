"""Text-to-speech provider interface + MMS-TTS (VITS) implementation.

facebook/mms-tts-<lang> models are used as the initial open-source,
self-hostable TTS backend (build spec: "Initial implementation may use a
suitable open-source or managed TTS engine depending on latency and
language quality"). Swapping to a different engine is a new class behind
this same interface, not a redesign.

Also holds the STREAMING TTS interface (StreamingTTSProvider) and three
implementations:
  - StreamingMmsTTSProvider: a real, working streaming wrapper around the
    existing (already-resident) MMS-TTS provider. VITS is non-
    autoregressive (it produces the whole waveform in one inference call,
    not incrementally), so true generate-while-streaming isn't something
    this model can do — this class is honest about that: it synthesizes
    the full utterance once, then CHUNKS the output into ordered,
    cancellable pieces (build spec section 13's ~300-800ms chunks) for
    delivery, which is what the rest of the streaming pipeline (audio
    output buffer, barge-in cancellation) actually needs from a TTS
    provider's interface regardless of whether generation itself is
    incremental.
  - Qwen3TTSProvider / CosyVoice3Provider: the build spec's new primary/
    alternative TTS models. Written against their documented APIs
    (verified against live model cards; see docs/MODEL_LICENSE_MATRIX.md)
    but NOT downloaded in this build — see ModelNotAvailableError.
  - IndicParlerTTSProvider / PiperTTSProvider: CPU-feasible candidates
    investigated after Qwen3-TTS/CosyVoice3 turned out to be GPU-only and
    this build's real deployment target is a CPU-only VPS. Both written
    against their real, verified APIs; neither downloaded in this build —
    see ModelNotAvailableError and docs/MODEL_LICENSE_MATRIX.md for each
    one's real, current license status (IndicParlerTTS: Apache-2.0,
    confirmed clean. Piper: MIT engine, but the specific Tamil voice
    checkpoint's dataset license is UNVERIFIED — see the class docstring).
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from collections.abc import Iterator
from pathlib import Path

import numpy as np

from .model_lifecycle import ModelHealth, ModelLifecycle, ModelMetadata, ModelNotAvailableError
from .types import SynthesizedAudio

DEFAULT_CACHE_DIR = Path(__file__).resolve().parents[2] / "models" / "hf"

_LANG_TO_MMS_MODEL = {
    "en": "facebook/mms-tts-eng",
    "ta": "facebook/mms-tts-tam",
    "ml": "facebook/mms-tts-mal",
}


class TTSProvider(ABC):
    @abstractmethod
    def synthesize(self, text: str, lang: str) -> SynthesizedAudio: ...


class MmsTTSProvider(TTSProvider):
    """Lazily loads one VITS model per language on first use (each is
    ~150-200MB; loading all three upfront would waste memory for a session
    that only ever needs one direction)."""

    def __init__(self, cache_dir: Path | str = DEFAULT_CACHE_DIR):
        self._cache_dir = str(cache_dir)
        self._models: dict[str, object] = {}
        self._tokenizers: dict[str, object] = {}

    def _load(self, lang: str):
        if lang in self._models:
            return self._models[lang], self._tokenizers[lang]
        if lang not in _LANG_TO_MMS_MODEL:
            raise ValueError(f"no TTS model configured for language {lang!r}")

        from transformers import (  # local import: heavy optional dep
            AutoTokenizer,
            VitsModel,
        )

        model_id = _LANG_TO_MMS_MODEL[lang]
        model = VitsModel.from_pretrained(model_id, cache_dir=self._cache_dir)
        tokenizer = AutoTokenizer.from_pretrained(model_id, cache_dir=self._cache_dir)
        self._models[lang] = model
        self._tokenizers[lang] = tokenizer
        return model, tokenizer

    def synthesize(self, text: str, lang: str) -> SynthesizedAudio:
        import torch

        model, tokenizer = self._load(lang)
        inputs = tokenizer(text, return_tensors="pt")
        with torch.no_grad():
            waveform = model(**inputs).waveform
        samples = waveform.squeeze().cpu().numpy().astype(np.float32)
        return SynthesizedAudio(samples=samples, sample_rate=model.config.sampling_rate)


class StreamingTTSProvider(ModelLifecycle):
    @abstractmethod
    def stream(self, text: str, lang: str, utterance_id: str) -> Iterator[SynthesizedAudio]:
        """Yields successive audio chunks for `text`, in order. Callers
        (audio_output_buffer.py) MUST be able to stop iterating at any
        time (barge-in) — a plain Python generator supports this for
        free: an abandoned `for chunk in stream(...)` loop simply never
        calls next() again, and any real background work a provider does
        must be tied to the generator's own lifetime (e.g. via
        try/finally around the yield loop), not a separate uncancellable
        thread."""

    def cancel(self, utterance_id: str) -> None:
        """Default no-op — sufficient for a provider whose stream() does
        all its work in the generator body (see stream()'s docstring).
        Override only if a provider hands work to a separate
        thread/process it must explicitly interrupt."""


# ~300-800ms is the build spec's own recommended TTS output chunk range
# (section 5); 500ms is the config default (section 27's AI_TTS_CHUNK_MS).
_DEFAULT_TTS_CHUNK_MS = 500.0


class StreamingMmsTTSProvider(StreamingTTSProvider):
    """Wraps the existing MmsTTSProvider (already resident, no new model
    weights) to satisfy the streaming interface honestly: VITS is
    non-autoregressive, so this synthesizes the FULL utterance in one
    call — real, working synthesis, not a stub — then yields it back out
    in ordered ~chunk_ms pieces. cancel() sets a flag the generator checks
    between chunks so an in-flight stream() stops emitting further audio
    on the next iteration after barge-in, without needing to interrupt
    the (already-finished, by that point) synthesis call itself."""

    def __init__(self, inner: MmsTTSProvider | None = None, chunk_ms: float = _DEFAULT_TTS_CHUNK_MS):
        super().__init__()
        self._inner = inner or MmsTTSProvider()
        self._chunk_ms = chunk_ms
        self._cancelled_utterances: set[str] = set()

    def load(self) -> None:
        self._loaded = True  # MmsTTSProvider lazily loads per-language on first synthesize() call

    def health(self) -> ModelHealth:
        return ModelHealth(healthy=True, loaded=True, detail="lazy per-language loading (see MmsTTSProvider)")

    def metadata(self) -> ModelMetadata:
        return ModelMetadata(
            provider_id="mms-tts",
            checkpoint="facebook/mms-tts-<lang>",
            version="vits",
            code_license="Apache-2.0",  # transformers' VITS implementation
            # Verified directly against facebook/mms-tts-eng's live model card, 2026-09-25:
            # cc-by-nc-4.0 — non-commercial. See docs/MODEL_LICENSE_MATRIX.md; this is an
            # existing, already-shipped dependency, not introduced by this pass.
            weights_license="CC-BY-NC-4.0",
            commercial_use=False,
            redistribution=True,
            attribution_required=True,
            source_url="https://huggingface.co/facebook/mms-tts-eng",
            verified_date="2026-09-25",
            certified=True,  # existing, live-verified fallback TTS for en/ta
            notes="Existing TTS provider; NON-COMMERCIAL license — see docs/MODEL_LICENSE_MATRIX.md.",
        )

    def cancel(self, utterance_id: str) -> None:
        self._cancelled_utterances.add(utterance_id)

    def stream(self, text: str, lang: str, utterance_id: str) -> Iterator[SynthesizedAudio]:
        try:
            full = self._inner.synthesize(text, lang)
            chunk_samples = max(1, int(self._chunk_ms / 1000 * full.sample_rate))
            for start in range(0, len(full.samples), chunk_samples):
                if utterance_id in self._cancelled_utterances:
                    return
                yield SynthesizedAudio(
                    samples=full.samples[start : start + chunk_samples], sample_rate=full.sample_rate,
                )
        finally:
            self._cancelled_utterances.discard(utterance_id)


class Qwen3TTSProvider(StreamingTTSProvider):
    """Qwen/Qwen3-TTS-12Hz-1.7B-Base (build spec section 3) — API verified
    against the live model card (2026-09-25):

        from qwen_tts import Qwen3TTSModel
        model = Qwen3TTSModel.from_pretrained(
            "Qwen/Qwen3-TTS-12Hz-1.7B-Base", device_map="cuda:0", dtype=torch.bfloat16,
        )
        wavs, sr = model.generate_voice_clone(
            text=..., language=..., ref_audio=..., ref_text=...,
        )

    IMPORTANT (verified, not assumed): the model card advertises "Extreme
    Low-Latency Streaming Generation" as a feature, but a distinct
    streaming method name/signature is NOT documented anywhere on the
    public model card as of the verification date above — only the batch
    `generate_voice_clone()`/`generate_custom_voice()`/
    `generate_voice_design()` methods have documented signatures. This
    class therefore implements the real, verified batch path and satisfies
    the StreamingTTSProvider interface the same honest way
    StreamingMmsTTSProvider does (synthesize once, yield back in ordered
    chunks) rather than inventing an unverified streaming call. Finding
    and wiring up the real incremental API is future work once GPU access
    exists to actually test it against.

    `generate_voice_clone()` also requires a reference audio + reference
    text (voice-cloning architecture) — this build has no doctor voice
    sample to clone from, so a real deployment would need a fixed default
    reference voice per supported language, a genuinely open design
    question this pass does not resolve (see docs/ai/streaming.md).

    Not downloaded in this build.
    """

    CHECKPOINT = "Qwen/Qwen3-TTS-12Hz-1.7B-Base"

    def __init__(self, chunk_ms: float = _DEFAULT_TTS_CHUNK_MS, ref_audio: str | None = None, ref_text: str | None = None):
        super().__init__()
        self._chunk_ms = chunk_ms
        self._ref_audio = ref_audio
        self._ref_text = ref_text
        self._model = None
        self._cancelled_utterances: set[str] = set()

    def load(self) -> None:
        if self._loaded:
            return
        if os.environ.get("AI_ALLOW_MODEL_DOWNLOAD", "false").lower() != "true":
            raise ModelNotAvailableError(
                f"{self.CHECKPOINT}: AI_ALLOW_MODEL_DOWNLOAD is not 'true' — this build never "
                "downloads new model weights implicitly. TTSRouter falls back to the configured "
                "fallback provider (CosyVoice3, else MMS-TTS) instead."
            )
        try:
            import torch
            from qwen_tts import Qwen3TTSModel
        except ImportError as e:
            raise ModelNotAvailableError(f"{self.CHECKPOINT}: required package not installed ({e})") from e
        if not torch.cuda.is_available():
            raise ModelNotAvailableError(f"{self.CHECKPOINT}: no CUDA device available")
        if not self._ref_audio or not self._ref_text:
            raise ModelNotAvailableError(
                f"{self.CHECKPOINT}: generate_voice_clone() requires a reference audio+text; "
                "none configured (see class docstring's 'open design question')."
            )

        import time as _time

        t0 = _time.monotonic()
        self._model = Qwen3TTSModel.from_pretrained(self.CHECKPOINT, device_map="cuda:0", dtype=torch.bfloat16)
        self._load_seconds = _time.monotonic() - t0
        self._loaded = True

    def health(self) -> ModelHealth:
        return ModelHealth(healthy=self._loaded, loaded=self._loaded,
                            detail="ok" if self._loaded else "not loaded (see load())")

    def metadata(self) -> ModelMetadata:
        return ModelMetadata(
            provider_id="qwen3-tts",
            checkpoint=self.CHECKPOINT,
            version="12Hz-1.7B-Base",
            code_license="Apache-2.0",
            weights_license="Apache-2.0",
            commercial_use=True,
            redistribution=True,
            attribution_required=True,
            source_url="https://huggingface.co/Qwen/Qwen3-TTS-12Hz-1.7B-Base",
            verified_date="2026-09-25",
            certified=False,
            notes="Not downloaded in this build; requires GPU + a reference voice clip per language (open design question); true streaming method not publicly documented as of verification date.",
        )

    def cancel(self, utterance_id: str) -> None:
        self._cancelled_utterances.add(utterance_id)

    def stream(self, text: str, lang: str, utterance_id: str) -> Iterator[SynthesizedAudio]:
        if not self._loaded:
            raise RuntimeError("load() must be called before stream()")
        try:
            wavs, sr = self._model.generate_voice_clone(
                text=text, language=lang, ref_audio=self._ref_audio, ref_text=self._ref_text,
            )
            samples = np.asarray(wavs[0], dtype=np.float32)
            chunk_samples = max(1, int(self._chunk_ms / 1000 * sr))
            for start in range(0, len(samples), chunk_samples):
                if utterance_id in self._cancelled_utterances:
                    return
                yield SynthesizedAudio(samples=samples[start : start + chunk_samples], sample_rate=sr)
        finally:
            self._cancelled_utterances.discard(utterance_id)

    def synthesize(self, text: str, lang: str) -> SynthesizedAudio:
        """Adapter satisfying the OLD, non-streaming TTSProvider interface
        (build_default_pipeline()/orchestrator.py expect `.synthesize()`,
        not `.stream()`) by consuming this provider's own stream() to
        completion and concatenating the result. Real generation happens
        exactly once either way (generate_voice_clone() is a single batch
        call regardless — see stream()'s own docstring), so this adds no
        extra inference cost over calling stream() directly."""
        import uuid

        utterance_id = f"sync-{uuid.uuid4()}"
        chunks = list(self.stream(text, lang, utterance_id))
        if not chunks:
            return SynthesizedAudio(samples=np.zeros((0,), dtype=np.float32), sample_rate=16000)
        samples = np.concatenate([c.samples for c in chunks])
        return SynthesizedAudio(samples=samples, sample_rate=chunks[0].sample_rate)


class CosyVoice3Provider(StreamingTTSProvider):
    """FunAudioLLM/Fun-CosyVoice3-0.5B-2512 (build spec section 3
    alternative TTS) — API verified against the live model card
    (2026-09-25):

        from cosyvoice.cli.cosyvoice import AutoModel
        cosyvoice = AutoModel(model_dir='pretrained_models/Fun-CosyVoice3-0.5B')
        # inference_zero_shot() / inference_cross_lingual() / inference_instruct2()
        # each accept stream=True/False — a REAL, documented streaming flag
        # (unlike Qwen3-TTS above, whose streaming call signature isn't
        # publicly documented).

    IMPORTANT (verified, not assumed): every documented inference method
    is a voice-cloning/cross-lingual-cloning method requiring a reference
    speaker; there is no documented "just synthesize this text in this
    language with a default voice" entry point. Same open design question
    as Qwen3TTSProvider (a fixed default reference voice per language)
    applies here. This also requires the `third_party/Matcha-TTS`
    dependency and a local `AutoModel` checkpoint directory, not a plain
    `from_pretrained(repo_id)` HuggingFace call — heavier packaging than
    every other provider in this file.

    Not downloaded in this build.
    """

    CHECKPOINT = "FunAudioLLM/Fun-CosyVoice3-0.5B-2512"

    def __init__(self, model_dir: str | None = None, chunk_ms: float = _DEFAULT_TTS_CHUNK_MS,
                 ref_audio: str | None = None, ref_text: str | None = None):
        super().__init__()
        self._model_dir = model_dir
        self._chunk_ms = chunk_ms
        self._ref_audio = ref_audio
        self._ref_text = ref_text
        self._model = None
        self._cancelled_utterances: set[str] = set()

    def load(self) -> None:
        if self._loaded:
            return
        if os.environ.get("AI_ALLOW_MODEL_DOWNLOAD", "false").lower() != "true":
            raise ModelNotAvailableError(
                f"{self.CHECKPOINT}: AI_ALLOW_MODEL_DOWNLOAD is not 'true' — this build never "
                "downloads new model weights implicitly. TTSRouter falls back to MMS-TTS instead."
            )
        if not self._model_dir:
            raise ModelNotAvailableError(
                f"{self.CHECKPOINT}: no local model_dir configured — CosyVoice3 loads from a "
                "local checkpoint directory, not a bare HuggingFace repo id."
            )
        try:
            from cosyvoice.cli.cosyvoice import AutoModel
        except ImportError as e:
            raise ModelNotAvailableError(
                f"{self.CHECKPOINT}: 'cosyvoice' package (+ third_party/Matcha-TTS on path) not "
                f"installed ({e})"
            ) from e
        if not self._ref_audio or not self._ref_text:
            raise ModelNotAvailableError(
                f"{self.CHECKPOINT}: every documented inference method requires a reference "
                "speaker; none configured (see class docstring's 'open design question')."
            )

        import time as _time

        t0 = _time.monotonic()
        self._model = AutoModel(model_dir=self._model_dir)
        self._load_seconds = _time.monotonic() - t0
        self._loaded = True

    def health(self) -> ModelHealth:
        return ModelHealth(healthy=self._loaded, loaded=self._loaded,
                            detail="ok" if self._loaded else "not loaded (see load())")

    def metadata(self) -> ModelMetadata:
        return ModelMetadata(
            provider_id="cosyvoice3",
            checkpoint=self.CHECKPOINT,
            version="0.5B-2512",
            code_license="Apache-2.0",
            weights_license="Apache-2.0",
            commercial_use=True,
            redistribution=True,
            attribution_required=True,
            source_url="https://huggingface.co/FunAudioLLM/Fun-CosyVoice3-0.5B-2512",
            verified_date="2026-09-25",
            certified=False,
            notes="Not downloaded in this build; needs a local checkpoint dir + third_party/Matcha-TTS + a reference voice clip per language (open design question).",
        )

    def cancel(self, utterance_id: str) -> None:
        self._cancelled_utterances.add(utterance_id)

    def stream(self, text: str, lang: str, utterance_id: str) -> Iterator[SynthesizedAudio]:
        if not self._loaded:
            raise RuntimeError("load() must be called before stream()")
        try:
            for piece in self._model.inference_cross_lingual(
                tts_text=text, prompt_speech_16k=self._ref_audio, stream=True,
            ):
                if utterance_id in self._cancelled_utterances:
                    return
                yield SynthesizedAudio(
                    samples=np.asarray(piece["tts_speech"], dtype=np.float32),
                    sample_rate=self._model.sample_rate,
                )
        finally:
            self._cancelled_utterances.discard(utterance_id)


_INDIC_PARLER_TTS_VOICE_DESCRIPTIONS = {
    # Named speakers documented on the model's own card. Sentence-length
    # description prompts are how this model selects a voice — there is
    # no separate reference-audio-clip requirement (unlike Qwen3-TTS/
    # CosyVoice3's voice-cloning architecture), so this provider has none
    # of those classes' "open design question."
    "ta": "Jaya's voice is clear, with excellent audio quality and expressive delivery.",
    "en": "A clear, natural English voice with excellent audio quality.",
}


class IndicParlerTTSProvider(TTSProvider, ModelLifecycle):
    """ai4bharat/indic-parler-tts (build spec section 3 alternative,
    investigated after Qwen3-TTS/CosyVoice3 turned out GPU-only). API
    verified against the live model card (2026-09-25):

        import torch
        from parler_tts import ParlerTTSForConditionalGeneration
        from transformers import AutoTokenizer

        model = ParlerTTSForConditionalGeneration.from_pretrained(
            "ai4bharat/indic-parler-tts",
        ).to(device)
        tokenizer = AutoTokenizer.from_pretrained("ai4bharat/indic-parler-tts")
        description_tokenizer = AutoTokenizer.from_pretrained(
            model.config.text_encoder._name_or_path,
        )
        # description selects the voice via natural language, e.g.
        # "Jaya's voice is clear, with excellent audio quality..."
        generation = model.generate(
            input_ids=description_ids, attention_mask=description_mask,
            prompt_input_ids=prompt_ids, prompt_attention_mask=prompt_mask,
        )

    License: Apache-2.0, explicitly states commercial use is permitted —
    verified directly against the live model card (2026-09-25). This is
    the one candidate in this file with an UNAMBIGUOUSLY clean commercial
    license AND confirmed real Tamil support (named speakers "Jaya"/
    "Kavitha") AND a documented CPU fallback path in its own example code
    (`device = "cuda:0" if torch.cuda.is_available() else "cpu"`) — unlike
    Qwen3-TTS/CosyVoice3, which have no CPU path at all.

    Real, honest caveat: 0.9B parameters. CPU inference has NOT been
    benchmarked in this build (not downloaded — see ModelNotAvailableError)
    and is expected to take multiple seconds per utterance on CPU, not
    real-time — see docs/ai/latency.md once measured. Requires the
    separate `parler-tts` package (`pip install
    git+https://github.com/huggingface/parler-tts.git`), not just
    `transformers`.
    """

    CHECKPOINT = "ai4bharat/indic-parler-tts"

    def __init__(self, cache_dir: Path | str = DEFAULT_CACHE_DIR):
        ModelLifecycle.__init__(self)
        self._cache_dir = str(cache_dir)
        self._model = None
        self._tokenizer = None
        self._description_tokenizer = None
        self._device = "cpu"

    def load(self) -> None:
        if self._loaded:
            return
        if os.environ.get("AI_ALLOW_MODEL_DOWNLOAD", "false").lower() != "true":
            raise ModelNotAvailableError(
                f"{self.CHECKPOINT}: AI_ALLOW_MODEL_DOWNLOAD is not 'true' — this build never "
                "downloads new model weights implicitly."
            )
        try:
            import torch
            from parler_tts import ParlerTTSForConditionalGeneration
            from transformers import AutoTokenizer
        except ImportError as e:
            raise ModelNotAvailableError(
                f"{self.CHECKPOINT}: required package not installed ({e}) — needs 'parler-tts' "
                "in addition to 'transformers'"
            ) from e

        import time as _time

        t0 = _time.monotonic()
        self._device = "cuda:0" if torch.cuda.is_available() else "cpu"
        self._model = ParlerTTSForConditionalGeneration.from_pretrained(
            self.CHECKPOINT, cache_dir=self._cache_dir
        ).to(self._device)
        self._tokenizer = AutoTokenizer.from_pretrained(self.CHECKPOINT, cache_dir=self._cache_dir)
        self._description_tokenizer = AutoTokenizer.from_pretrained(
            self._model.config.text_encoder._name_or_path, cache_dir=self._cache_dir
        )
        self._load_seconds = _time.monotonic() - t0
        self._loaded = True

    def health(self) -> ModelHealth:
        return ModelHealth(healthy=self._loaded, loaded=self._loaded,
                            detail="ok" if self._loaded else "not loaded (see load())")

    def metadata(self) -> ModelMetadata:
        return ModelMetadata(
            provider_id="indic-parler-tts",
            checkpoint=self.CHECKPOINT,
            version="0.9B",
            code_license="Apache-2.0",
            weights_license="Apache-2.0",
            commercial_use=True,
            redistribution=True,
            attribution_required=True,
            source_url="https://huggingface.co/ai4bharat/indic-parler-tts",
            verified_date="2026-09-25",
            certified=False,
            notes="License confirmed clean and Tamil confirmed supported; CPU-capable but latency not benchmarked (expected multi-second per utterance, not real-time) — not downloaded/certified this pass.",
        )

    def synthesize(self, text: str, lang: str) -> SynthesizedAudio:
        if not self._loaded:
            raise RuntimeError("load() must be called before synthesize()")
        description = _INDIC_PARLER_TTS_VOICE_DESCRIPTIONS.get(lang, _INDIC_PARLER_TTS_VOICE_DESCRIPTIONS["en"])

        description_ids = self._description_tokenizer(description, return_tensors="pt").to(self._device)
        prompt_ids = self._tokenizer(text, return_tensors="pt").to(self._device)

        generation = self._model.generate(
            input_ids=description_ids.input_ids, attention_mask=description_ids.attention_mask,
            prompt_input_ids=prompt_ids.input_ids, prompt_attention_mask=prompt_ids.attention_mask,
        )
        samples = generation.cpu().numpy().squeeze().astype(np.float32)
        return SynthesizedAudio(samples=samples, sample_rate=self._model.config.sampling_rate)


class PiperTTSProvider(TTSProvider, ModelLifecycle):
    """Piper (rhasspy/piper, MIT — archived Oct 2025; actively-maintained
    successor OHF-Voice/piper1-gpl is GPL-3.0). Invoked via its CLI
    (`piper --model <voice.onnx> --output_file <wav>`, text on stdin) via
    subprocess, NEVER imported as a Python library into this process —
    deliberately, so this provider stays safe to use regardless of which
    engine version (the old MIT release or the new GPL one) is actually
    installed: GPL-3.0's copyleft obligations attach to linking/derivative
    works, not to invoking a separate CLI process and reading its output
    (the standard "mere aggregation" pattern commercial products already
    use for other GPL command-line tools, e.g. ffmpeg builds) — see
    docs/MODEL_LICENSE_MATRIX.md for the full reasoning. This class does
    NOT `import piper` anywhere.

    Real, HONEST, UNRESOLVED gap: Piper's own community-contributed Tamil
    voice (`ta_IN-Valluvar-medium.onnx`, referenced in
    rhasspy/piper-voices) has a per-voice license that its own listing
    defers to "the original dataset license" — which this pass could NOT
    verify despite real effort (no dataset name/license found via the
    available research tools). The MIT/GPL question above is about the
    Piper ENGINE only; the VOICE checkpoint's commercial-use status is
    SEPARATE and UNVERIFIED. Do not enable this in production without
    resolving that specific question first — see
    docs/MODEL_LICENSE_MATRIX.md's "Unknown = NOT APPROVED" rule.

    `checkpoint` is a local path to a `.onnx` voice file (Piper voices are
    not loaded via HuggingFace `from_pretrained()` — they are downloaded
    once as a pair of files, `<voice>.onnx` + `<voice>.onnx.json`, and
    referenced by local path).
    """

    def __init__(self, checkpoint: str | None = None, piper_executable: str = "piper"):
        ModelLifecycle.__init__(self)
        self._checkpoint = checkpoint
        self._piper_executable = piper_executable

    def load(self) -> None:
        if self._loaded:
            return
        if os.environ.get("AI_ALLOW_MODEL_DOWNLOAD", "false").lower() != "true":
            raise ModelNotAvailableError(
                "piper: AI_ALLOW_MODEL_DOWNLOAD is not 'true' — this build never downloads new "
                "voice checkpoints implicitly."
            )
        if not self._checkpoint:
            raise ModelNotAvailableError(
                "piper: no local voice checkpoint (.onnx) path configured — Piper voices are "
                "downloaded once as local files, not fetched via from_pretrained()."
            )
        import shutil

        if shutil.which(self._piper_executable) is None:
            raise ModelNotAvailableError(
                f"piper: the '{self._piper_executable}' executable was not found on PATH "
                "(pip install piper-tts, or install a piper1-gpl build)."
            )
        if not Path(self._checkpoint).is_file():
            raise ModelNotAvailableError(f"piper: voice checkpoint file not found at {self._checkpoint!r}")
        self._loaded = True

    def health(self) -> ModelHealth:
        return ModelHealth(healthy=self._loaded, loaded=self._loaded,
                            detail="ok" if self._loaded else "not loaded (see load())")

    def metadata(self) -> ModelMetadata:
        return ModelMetadata(
            provider_id="piper",
            checkpoint=self._checkpoint or "unconfigured",
            version="onnx",
            code_license="MIT (archived rhasspy/piper) — successor OHF-Voice/piper1-gpl is GPL-3.0; invoked via CLI subprocess only, never imported as a library, to stay safe under either",
            weights_license="UNVERIFIED per-voice — see class docstring",
            commercial_use=False,  # deliberately conservative: the specific Tamil voice's license is unverified — see docstring
            redistribution=False,
            attribution_required=True,
            source_url="https://huggingface.co/rhasspy/piper-voices",
            verified_date="2026-09-25",
            certified=False,
            notes="Engine (MIT archived / GPL-3.0 current, safe via CLI subprocess) is not the blocker — the specific voice checkpoint's dataset license is UNVERIFIED. Do not enable in production without resolving this.",
        )

    def synthesize(self, text: str, lang: str) -> SynthesizedAudio:
        if not self._loaded:
            raise RuntimeError("load() must be called before synthesize()")
        import subprocess
        import tempfile
        import wave

        with tempfile.NamedTemporaryFile(suffix=".wav") as tmp:
            subprocess.run(
                [self._piper_executable, "--model", self._checkpoint, "--output_file", tmp.name],
                input=text.encode("utf-8"),
                check=True,
                capture_output=True,
            )
            with wave.open(tmp.name, "rb") as wav_file:
                sample_rate = wav_file.getframerate()
                raw = wav_file.readframes(wav_file.getnframes())
        samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
        return SynthesizedAudio(samples=samples, sample_rate=sample_rate)
