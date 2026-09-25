"""AudioOutputBuffer (build spec section 14): a small jitter/output buffer
that preserves audio ordering, sequences chunks, removes stale chunks,
handles late chunks, prevents duplicate playback, supports cancellation,
and detects a missing chunk in the sequence — all keyed by
(session_id, utterance_id, sequence_number), never by raw wall-clock
timestamp alone (build spec's explicit instruction).

One instance per utterance being played out. A new utterance means a new
instance (or reset()) — cross-utterance sequencing (stopping the OLD
utterance's buffer when a new one starts, i.e. barge-in) is
streaming_pipeline.py's job, one level up.
"""

from __future__ import annotations

from dataclasses import dataclass

from .types import AudioChunk


@dataclass
class DeliveryResult:
    deliverable: list[AudioChunk]  # ready to play, in order
    dropped_stale: int = 0
    dropped_duplicate: int = 0
    missing_sequence_detected: bool = False


class AudioOutputBuffer:
    def __init__(self, utterance_id: str, max_out_of_order_wait: int = 5):
        self._utterance_id = utterance_id
        self._next_expected_seq = 0
        self._pending: dict[int, AudioChunk] = {}
        self._delivered_seqs: set[int] = set()
        self._cancelled = False
        self._max_out_of_order_wait = max_out_of_order_wait

    @property
    def utterance_id(self) -> str:
        return self._utterance_id

    @property
    def is_cancelled(self) -> bool:
        return self._cancelled

    def cancel(self) -> None:
        self._cancelled = True
        self._pending.clear()

    def push(self, chunk: AudioChunk) -> DeliveryResult:
        if chunk.utterance_id != self._utterance_id:
            raise ValueError(
                f"chunk for utterance {chunk.utterance_id!r} pushed into buffer for {self._utterance_id!r}"
            )
        if self._cancelled:
            return DeliveryResult(deliverable=[])

        if chunk.sequence_number in self._delivered_seqs:
            return DeliveryResult(deliverable=[], dropped_duplicate=1)
        if chunk.sequence_number < self._next_expected_seq:
            return DeliveryResult(deliverable=[], dropped_stale=1)

        self._pending[chunk.sequence_number] = chunk

        deliverable = self._drain_contiguous()
        missing_sequence_detected = False
        dropped_stale = 0

        if not deliverable and len(self._pending) >= self._max_out_of_order_wait:
            # We've waited long enough for `_next_expected_seq` while later
            # chunks piled up behind it — treat it as permanently missing
            # rather than stalling playback forever. Skip ahead to the
            # earliest chunk we actually have.
            missing_sequence_detected = True
            dropped_stale += 1  # the skipped seq, if it ever arrives late, is now stale by definition
            self._next_expected_seq = min(self._pending)
            deliverable = self._drain_contiguous()

        return DeliveryResult(
            deliverable=deliverable, dropped_stale=dropped_stale, missing_sequence_detected=missing_sequence_detected,
        )

    def _drain_contiguous(self) -> list[AudioChunk]:
        out = []
        while self._next_expected_seq in self._pending:
            chunk = self._pending.pop(self._next_expected_seq)
            out.append(chunk)
            self._delivered_seqs.add(self._next_expected_seq)
            self._next_expected_seq += 1
        return out
