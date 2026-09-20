"""Wires a subscribed LiveKit remote audio track through VAD-based turn
segmentation into the translation pipeline, and publishes the translated
result back as a new local audio track + a data-channel caption message.

Runs entirely off the asyncio event loop for I/O (LiveKit's AudioStream,
track publishing) but dispatches each pipeline.process() call — which is
synchronous, CPU-bound model inference — to a thread executor, so a
multi-hundred-millisecond translation never blocks audio delivery to other
participants or the room's signaling.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from livekit import rtc

from ..logging_setup import log
from .orchestrator import SAMPLE_RATE, TranslationPipeline
from .vad import FRAME_SAMPLES, SileroVAD, TurnSegmenter

CAPTIONS_TOPIC = "ayureze.captions"

# Diagnostic-only, off by default. Set AYUREZE_AUDIO_DIAG=1 to log
# per-frame audio/VAD/turn-segmenter state (never raw PCM, transcript,
# translated text, keys, or tokens — see _log_frame_diagnostics below)
# while debugging the LiveKit -> VAD -> STT integration path. Never
# enabled by default in production; see docs/ai/README.md for removal/
# promotion status of this instrumentation.
_AUDIO_DIAG_ENABLED = os.environ.get("AYUREZE_AUDIO_DIAG") == "1"

# EN<->TA is this build's primary supported pair (build spec section 5).
# Any other detected language (e.g. ml, when a Malayalam-capable STT/
# translation model is configured) still routes back to English, since a
# 3-way rotating target isn't part of the Day 6 scope.
_DEFAULT_TARGET_FOR = {"en": "ta"}


def target_language_for(source_lang: str) -> str:
    return _DEFAULT_TARGET_FOR.get(source_lang, "en")


class LiveAudioProcessor:
    def __init__(
        self,
        room: rtc.Room,
        pipeline: TranslationPipeline,
        logger: logging.Logger,
        session_id: str,
        executor: ThreadPoolExecutor | None = None,
        on_publish_start: Callable[[], None] | None = None,
        on_publish_end: Callable[[], None] | None = None,
    ):
        self._room = room
        self._pipeline = pipeline
        self._logger = logger
        self._session_id = session_id
        self._on_publish_start = on_publish_start
        self._on_publish_end = on_publish_end
        self._executor = executor or ThreadPoolExecutor(max_workers=2, thread_name_prefix="ayureze-pipeline")
        self._vad = SileroVAD()
        self._segmenter = TurnSegmenter(self._vad)
        self._sample_buffer = np.zeros((0,), dtype=np.float32)
        self._output_track: rtc.LocalAudioTrack | None = None
        self._output_source: rtc.AudioSource | None = None
        self._publish_task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()
        self._diag_raw_frame_count = 0
        self._diag_vad_frame_count = 0

    async def ensure_output_track_published(self) -> None:
        if self._output_track is not None:
            return
        self._output_source = rtc.AudioSource(sample_rate=SAMPLE_RATE, num_channels=1)
        self._output_track = rtc.LocalAudioTrack.create_audio_track("ai-translation", self._output_source)
        await self._room.local_participant.publish_track(self._output_track)

    async def handle_track(self, track: rtc.Track, participant: rtc.RemoteParticipant) -> None:
        """Consumes one subscribed remote audio track until the track ends
        or stop() is called. Safe to run as a background asyncio task."""
        await self.ensure_output_track_published()

        stream = rtc.AudioStream(track, sample_rate=SAMPLE_RATE, num_channels=1)
        try:
            async for event in stream:
                if self._stop_event.is_set():
                    break
                if _AUDIO_DIAG_ENABLED:
                    self._log_raw_frame_diagnostics(event.frame)
                await self._on_frame(event.frame, participant)
        finally:
            await stream.aclose()

    def _log_raw_frame_diagnostics(self, frame: rtc.AudioFrame) -> None:
        """Phase 1-3 instrumentation: the raw rtc.AudioFrame's own format,
        as delivered by AudioStream, before this module's int16->float32
        conversion. Never logs sample data itself, only shape/rate
        metadata. See _AUDIO_DIAG_ENABLED's docstring."""
        self._diag_raw_frame_count += 1
        if self._diag_raw_frame_count <= 5 or self._diag_raw_frame_count % 50 == 0:
            raw = np.frombuffer(frame.data, dtype=np.int16)
            raw_rms = float(np.sqrt(np.mean(np.square(raw.astype(np.float32))))) if raw.size else 0.0
            log(
                self._logger,
                logging.INFO,
                "audio_diag_raw_frame",
                event_type="audio_diag_raw_frame",
                session_id=self._session_id,
                frame_number=self._diag_raw_frame_count,
                sample_rate=frame.sample_rate,
                num_channels=frame.num_channels,
                samples_per_channel=frame.samples_per_channel,
                int16_element_count=len(frame.data),  # memoryview cast to "h" -> element count, not bytes
                raw_rms_int16=round(raw_rms, 3),
                raw_min_int16=int(raw.min()) if raw.size else None,
                raw_max_int16=int(raw.max()) if raw.size else None,
                duration_ms=round(frame.samples_per_channel / frame.sample_rate * 1000, 2) if frame.sample_rate else None,
            )

    async def _on_frame(self, frame: rtc.AudioFrame, participant: rtc.RemoteParticipant) -> None:
        samples = np.frombuffer(frame.data, dtype=np.int16).astype(np.float32) / 32768.0
        self._sample_buffer = np.concatenate([self._sample_buffer, samples])

        while self._sample_buffer.shape[0] >= FRAME_SAMPLES:
            chunk, self._sample_buffer = (
                self._sample_buffer[:FRAME_SAMPLES],
                self._sample_buffer[FRAME_SAMPLES:],
            )
            segment = self._segmenter.push(chunk)
            if _AUDIO_DIAG_ENABLED:
                self._log_vad_frame_diagnostics(chunk, segment)
            if segment is not None:
                # Fire-and-forget: don't block frame delivery on a
                # multi-hundred-ms pipeline run. _process_segment handles
                # its own barge-in cancellation of any prior publish.
                asyncio.create_task(self._process_segment(segment, participant))

    def _log_vad_frame_diagnostics(self, chunk: np.ndarray, segment: np.ndarray | None) -> None:
        """Phase 4-6 instrumentation: signal level, VAD decision, and
        turn-segmenter state for one VAD-sized chunk, read AFTER
        self._segmenter.push(chunk) already ran it through the VAD exactly
        once (see vad.py's SileroVAD.last_probability doc — never calls
        the model a second time, which would corrupt its recurrent
        state). Never logs the chunk's own sample data."""
        self._diag_vad_frame_count += 1
        rms = float(np.sqrt(np.mean(np.square(chunk)))) if chunk.size else 0.0
        log(
            self._logger,
            logging.INFO,
            "audio_diag_vad_frame",
            event_type="audio_diag_vad_frame",
            session_id=self._session_id,
            vad_frame_number=self._diag_vad_frame_count,
            rms=round(rms, 6),
            min_amplitude=round(float(chunk.min()), 6) if chunk.size else None,
            max_amplitude=round(float(chunk.max()), 6) if chunk.size else None,
            speech_probability=round(self._vad.last_probability, 4) if self._vad.last_probability is not None else None,
            vad_threshold=self._vad.threshold,
            turn_in_speech=self._segmenter.in_speech,
            turn_silence_run=self._segmenter.silence_run,
            segment_emitted=segment is not None,
            segment_sample_count=int(segment.shape[0]) if segment is not None else None,
        )

    async def _process_segment(self, segment: np.ndarray, participant: rtc.RemoteParticipant) -> None:
        loop = asyncio.get_event_loop()

        # Barge-in: if the previous translated-audio publish is still in
        # flight when new speech arrives, cancel it rather than letting
        # two translated utterances overlap — the build spec explicitly
        # warns against "overlapping translated speech creat[ing]
        # uncontrolled audio loops."
        if self._publish_task is not None and not self._publish_task.done():
            self._publish_task.cancel()

        if _AUDIO_DIAG_ENABLED:
            log(
                self._logger,
                logging.INFO,
                "audio_diag_segment_emitted",
                event_type="audio_diag_segment_emitted",
                session_id=self._session_id,
                segment_sample_count=int(segment.shape[0]),
                segment_duration_ms=round(segment.shape[0] / SAMPLE_RATE * 1000, 1),
            )
            diag_t0 = time.monotonic()

        try:
            result = await loop.run_in_executor(
                self._executor, self._pipeline.process_auto, segment, target_language_for, self._session_id
            )
        except Exception as e:  # noqa: BLE001 - one failed segment must not kill the stream
            log(
                self._logger,
                logging.ERROR,
                "pipeline_segment_failed",
                event_type="pipeline_segment_failed",
                session_id=self._session_id,
                error=str(e),
            )
            return

        if _AUDIO_DIAG_ENABLED:
            log(
                self._logger,
                logging.INFO,
                "audio_diag_pipeline_result",
                event_type="audio_diag_pipeline_result",
                session_id=self._session_id,
                pipeline_duration_ms=round((time.monotonic() - diag_t0) * 1000, 1),
                transcript_length=len(result.transcript.text),
                detected_language=result.transcript.language,
                translated_length=len(result.translation.translated_text),
                safety_safe=result.safety.safe,
                safety_reason_codes=result.safety.reason_codes,
                audio_generated=result.audio is not None,
            )

        await self._publish_captions(result, participant)

        if result.blocked:
            # Only the short, medical-content-free reason codes go in the
            # log (e.g. "unit_mismatch", "negation_mismatch") — never
            # result.safety.reasons, whose human-readable strings can
            # quote extracted numbers/units/terms from the actual
            # conversation. See docs/ai/README.md's safety-validator
            # logging section and docs/monitoring/privacy.md.
            log(
                self._logger,
                logging.WARNING,
                "translation_blocked_by_safety_validator",
                event_type="translation_blocked_by_safety_validator",
                session_id=self._session_id,
                validation_status=result.safety.status,
                reason_codes=result.safety.reason_codes,
            )
            return

        if result.audio is None:
            return

        self._publish_task = asyncio.create_task(self._publish_audio(result.audio))

    async def _publish_captions(self, result, participant: rtc.RemoteParticipant) -> None:
        payload = {
            "type": "caption",
            "session_id": self._session_id,
            "speaker_identity": participant.identity,
            "source_lang": result.transcript.language,
            "target_lang": result.translation.target_lang,
            "original_text": result.transcript.text,
            "translated_text": result.translation.translated_text if not result.blocked else None,
            "blocked": result.blocked,
            "timings_ms": result.timings_ms,
            "at": time.time(),
        }
        try:
            await self._room.local_participant.publish_data(
                json.dumps(payload).encode("utf-8"), reliable=True, topic=CAPTIONS_TOPIC
            )
        except Exception as e:  # noqa: BLE001 - captions are best-effort
            log(self._logger, logging.WARNING, "caption_publish_failed", error=str(e))

    async def _publish_audio(self, audio) -> None:
        if self._output_source is None:
            return
        pcm16 = np.clip(audio.samples * 32767.0, -32768, 32767).astype(np.int16)

        frame_len = 160  # 10ms at 16kHz
        if self._on_publish_start:
            self._on_publish_start()
        try:
            for start in range(0, len(pcm16), frame_len):
                chunk = pcm16[start : start + frame_len]
                if len(chunk) < frame_len:
                    chunk = np.pad(chunk, (0, frame_len - len(chunk)))
                frame = rtc.AudioFrame.create(sample_rate=SAMPLE_RATE, num_channels=1, samples_per_channel=frame_len)
                np.frombuffer(frame.data, dtype=np.int16)[:] = chunk
                await self._output_source.capture_frame(frame)
        except asyncio.CancelledError:
            # Barge-in cancelled this publish mid-flight — expected, not
            # an error.
            raise
        finally:
            if self._on_publish_end:
                self._on_publish_end()

    async def stop(self) -> None:
        self._stop_event.set()
        if self._publish_task is not None:
            self._publish_task.cancel()
