"""StreamingSessionPipeline (build spec sections 4 and 9): ties
CommitPolicy -> TranslationRouter -> SafetyCommitPolicy ->
TTSRouter/StreamingTTSProvider -> AudioOutputBuffer together via bounded
asyncio.Queue stages, one instance per LiveKit session (matching this
build's existing per-session isolation — see app/agent.py/registry.py).

This is a NEW, OPT-IN code path (see app/config.py's
ai_agent_streaming_pipeline_enabled, default False). The existing
whole-utterance pipeline (orchestrator.py/streaming.py) is untouched and
remains the default, live-verified path — build spec: "Do NOT remove
existing working functionality" / "Do not delete the existing
implementation until [new] passes equivalent regression tests." This class
is unit-tested against fake translation/TTS providers (this file's own
test suite); it has NOT been exercised against a real live LiveKit room in
this pass — see docs/ai/streaming.md's "What has not been verified."
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from ..logging_setup import log
from .audio_output_buffer import AudioOutputBuffer
from .safety_commit_policy import SafetyCommitPolicy, SafetyDecision
from .translation_router import RoutingError, TranslationRouter
from .tts_router import TTSRoutingError, TTSRouter
from .types import AudioChunk


@dataclass
class StreamingPipelineConfig:
    # Defaults match build spec section 16's own example limits exactly.
    translation_queue_size: int = 20
    safety_queue_size: int = 20
    tts_queue_size: int = 20
    audio_output_max_out_of_order_wait: int = 5


@dataclass
class CommittedPhrase:
    """One CommitPolicy-flushed phrase, ready for translation."""

    utterance_id: str
    source_text: str
    source_lang: str
    target_lang: str


@dataclass
class _TranslatedPhrase:
    utterance_id: str
    source_text: str  # the FULL accumulated source for this utterance so far — see _translation_worker's docstring
    translated_text: str
    source_lang: str
    target_lang: str


class StreamingSessionPipeline:
    def __init__(
        self,
        session_id: str,
        translation_router: TranslationRouter,
        tts_router: TTSRouter,
        safety_policy: SafetyCommitPolicy | None = None,
        config: StreamingPipelineConfig | None = None,
        logger: logging.Logger | None = None,
        on_audio_chunk: Callable[[AudioChunk], Awaitable[None]] | None = None,
        on_caption: Callable[[dict], Awaitable[None]] | None = None,
    ):
        self._session_id = session_id
        self._translation_router = translation_router
        self._tts_router = tts_router
        self._safety_policy = safety_policy or SafetyCommitPolicy()
        self._config = config or StreamingPipelineConfig()
        self._logger = logger or logging.getLogger("ayureze.ai-agent.streaming_pipeline")
        self._on_audio_chunk = on_audio_chunk
        self._on_caption = on_caption

        self._translation_queue: asyncio.Queue[CommittedPhrase] = asyncio.Queue(maxsize=self._config.translation_queue_size)
        self._safety_queue: asyncio.Queue[_TranslatedPhrase] = asyncio.Queue(maxsize=self._config.safety_queue_size)
        self._tts_queue: asyncio.Queue[_TranslatedPhrase] = asyncio.Queue(maxsize=self._config.tts_queue_size)

        # Text held back after a WAIT_FOR_MORE_CONTEXT decision, keyed by
        # utterance_id. On the next committed phrase for the SAME
        # utterance, the pipeline re-translates the WHOLE accumulated
        # source text (never concatenates two independently-translated
        # fragments — merging two separate translations word-for-word is
        # not linguistically sound; re-translating the full source is).
        self._pending_source_by_utterance: dict[str, str] = {}
        self._output_buffer: AudioOutputBuffer | None = None
        self._sequence_counter = 0
        self._tasks: list[asyncio.Task] = []

    async def start(self) -> None:
        self._tasks = [
            asyncio.create_task(self._translation_worker(), name="ayureze-streaming-translation"),
            asyncio.create_task(self._safety_worker(), name="ayureze-streaming-safety"),
            asyncio.create_task(self._tts_worker(), name="ayureze-streaming-tts"),
        ]

    async def stop(self) -> None:
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks = []

    def begin_utterance(self, utterance_id: str) -> None:
        """VAD speech-start / a genuinely new utterance beginning. Cancels
        any still-playing previous utterance's output — barge-in (build
        spec sections 13 and 18) — and clears that utterance's
        safety-hold buffer so a stale WAIT never leaks into the new one."""
        if self._output_buffer is not None and not self._output_buffer.is_cancelled:
            self._output_buffer.cancel()
        self._pending_source_by_utterance.clear()
        self._output_buffer = AudioOutputBuffer(
            utterance_id=utterance_id, max_out_of_order_wait=self._config.audio_output_max_out_of_order_wait,
        )
        self._sequence_counter = 0

    async def submit_committed_phrase(self, phrase: CommittedPhrase) -> None:
        """Backpressure (build spec section 16): if the translation queue
        is full, drop the OLDEST already-queued phrase for the SAME
        utterance (superseded context — a newer phrase for that utterance
        makes an older queued one redundant), never a phrase belonging to
        a different/newer utterance, and never silently drop by picking
        an arbitrary victim."""
        try:
            self._translation_queue.put_nowait(phrase)
        except asyncio.QueueFull:
            self._drop_oldest_same_key(self._translation_queue, phrase.utterance_id)
            await self._translation_queue.put(phrase)

    @staticmethod
    def _drop_oldest_same_key(queue: asyncio.Queue, utterance_id: str) -> None:
        items = []
        dropped = False
        while not queue.empty():
            item = queue.get_nowait()
            if not dropped and item.utterance_id == utterance_id:
                dropped = True
                continue
            items.append(item)
        for item in items:
            queue.put_nowait(item)

    async def _put_bounded(self, queue: asyncio.Queue, item) -> None:
        try:
            queue.put_nowait(item)
        except asyncio.QueueFull:
            self._drop_oldest_same_key(queue, item.utterance_id)
            await queue.put(item)

    async def _translation_worker(self) -> None:
        while True:
            phrase = await self._translation_queue.get()
            try:
                await self._handle_committed_phrase(phrase)
            except Exception:  # noqa: BLE001 - one bad phrase must not kill the worker loop
                log(self._logger, logging.ERROR, "streaming_translation_worker_failed",
                    session_id=self._session_id, utterance_id=phrase.utterance_id)
            finally:
                self._translation_queue.task_done()

    async def _handle_committed_phrase(self, phrase: CommittedPhrase) -> None:
        merged_source = (
            self._pending_source_by_utterance.get(phrase.utterance_id, "") + " " + phrase.source_text
        ).strip()
        try:
            translated_text, _record = self._translation_router.route(phrase.source_lang, phrase.target_lang, merged_source)
        except RoutingError as e:
            log(self._logger, logging.WARNING, "streaming_translation_routing_failed",
                session_id=self._session_id, utterance_id=phrase.utterance_id, error=str(e))
            self._pending_source_by_utterance.pop(phrase.utterance_id, None)
            return

        await self._put_bounded(self._safety_queue, _TranslatedPhrase(
            utterance_id=phrase.utterance_id, source_text=merged_source, translated_text=translated_text,
            source_lang=phrase.source_lang, target_lang=phrase.target_lang,
        ))

    async def _safety_worker(self) -> None:
        while True:
            translated = await self._safety_queue.get()
            try:
                await self._handle_translated_phrase(translated)
            except Exception:  # noqa: BLE001
                log(self._logger, logging.ERROR, "streaming_safety_worker_failed",
                    session_id=self._session_id, utterance_id=translated.utterance_id)
            finally:
                self._safety_queue.task_done()

    async def _handle_translated_phrase(self, translated: _TranslatedPhrase) -> None:
        result = self._safety_policy.evaluate(
            translated.source_text, translated.translated_text,
            source_lang=translated.source_lang, target_lang=translated.target_lang,
        )

        if result.decision == SafetyDecision.WAIT_FOR_MORE_CONTEXT:
            self._pending_source_by_utterance[translated.utterance_id] = translated.source_text
            return

        self._pending_source_by_utterance.pop(translated.utterance_id, None)

        if self._on_caption:
            await self._on_caption({
                "utterance_id": translated.utterance_id,
                "source_lang": translated.source_lang,
                "target_lang": translated.target_lang,
                "original_text": translated.source_text,
                "translated_text": translated.translated_text if result.decision == SafetyDecision.SAFE_TO_SPEAK else None,
                "blocked": result.decision == SafetyDecision.BLOCKED,
                "reason_codes": result.safety_check.reason_codes if result.safety_check else [],
            })

        if result.decision == SafetyDecision.BLOCKED:
            log(self._logger, logging.WARNING, "streaming_translation_blocked_by_safety_validator",
                session_id=self._session_id, utterance_id=translated.utterance_id,
                reason_codes=result.safety_check.reason_codes if result.safety_check else [])
            return

        await self._put_bounded(self._tts_queue, translated)

    async def _tts_worker(self) -> None:
        while True:
            translated = await self._tts_queue.get()
            try:
                await self._handle_safe_phrase(translated)
            except Exception:  # noqa: BLE001
                log(self._logger, logging.ERROR, "streaming_tts_worker_failed",
                    session_id=self._session_id, utterance_id=translated.utterance_id)
            finally:
                self._tts_queue.task_done()

    async def _handle_safe_phrase(self, translated: _TranslatedPhrase) -> None:
        buffer = self._output_buffer
        if buffer is None or buffer.utterance_id != translated.utterance_id:
            return  # a newer utterance has already superseded this one (barge-in) — drop, never speak stale audio

        try:
            provider, _record = self._tts_router.route_for_language(translated.target_lang, translated.source_lang)
        except TTSRoutingError as e:
            log(self._logger, logging.WARNING, "streaming_tts_routing_failed",
                session_id=self._session_id, utterance_id=translated.utterance_id, error=str(e))
            return

        for audio in provider.stream(translated.translated_text, translated.target_lang, translated.utterance_id):
            if buffer.is_cancelled or self._output_buffer is not buffer:
                provider.cancel(translated.utterance_id)
                break
            chunk = AudioChunk(
                session_id=self._session_id, utterance_id=translated.utterance_id,
                sequence_number=self._sequence_counter, samples=audio.samples,
                sample_rate=audio.sample_rate, is_final=False,
            )
            self._sequence_counter += 1
            delivery = buffer.push(chunk)
            for deliverable in delivery.deliverable:
                if self._on_audio_chunk:
                    await self._on_audio_chunk(deliverable)
