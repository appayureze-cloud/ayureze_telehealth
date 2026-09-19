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
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from livekit import rtc

from ..logging_setup import log
from .orchestrator import SAMPLE_RATE, TranslationPipeline
from .vad import FRAME_SAMPLES, SileroVAD, TurnSegmenter

CAPTIONS_TOPIC = "ayureze.captions"

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
                await self._on_frame(event.frame, participant)
        finally:
            await stream.aclose()

    async def _on_frame(self, frame: rtc.AudioFrame, participant: rtc.RemoteParticipant) -> None:
        samples = np.frombuffer(frame.data, dtype=np.int16).astype(np.float32) / 32768.0
        self._sample_buffer = np.concatenate([self._sample_buffer, samples])

        while self._sample_buffer.shape[0] >= FRAME_SAMPLES:
            chunk, self._sample_buffer = (
                self._sample_buffer[:FRAME_SAMPLES],
                self._sample_buffer[FRAME_SAMPLES:],
            )
            segment = self._segmenter.push(chunk)
            if segment is not None:
                # Fire-and-forget: don't block frame delivery on a
                # multi-hundred-ms pipeline run. _process_segment handles
                # its own barge-in cancellation of any prior publish.
                asyncio.create_task(self._process_segment(segment, participant))

    async def _process_segment(self, segment: np.ndarray, participant: rtc.RemoteParticipant) -> None:
        loop = asyncio.get_event_loop()

        # Barge-in: if the previous translated-audio publish is still in
        # flight when new speech arrives, cancel it rather than letting
        # two translated utterances overlap — the build spec explicitly
        # warns against "overlapping translated speech creat[ing]
        # uncontrolled audio loops."
        if self._publish_task is not None and not self._publish_task.done():
            self._publish_task.cancel()

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
