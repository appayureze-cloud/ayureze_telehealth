import numpy as np

from app.pipeline.audio_output_buffer import AudioOutputBuffer
from app.pipeline.types import AudioChunk


def _chunk(seq: int, utterance_id: str = "u1", is_final: bool = False) -> AudioChunk:
    return AudioChunk(
        session_id="s1", utterance_id=utterance_id, sequence_number=seq,
        samples=np.array([float(seq)], dtype=np.float32), sample_rate=16000, is_final=is_final,
    )


def test_in_order_chunks_are_delivered_immediately():
    buf = AudioOutputBuffer(utterance_id="u1")
    r0 = buf.push(_chunk(0))
    r1 = buf.push(_chunk(1))
    assert [c.sequence_number for c in r0.deliverable] == [0]
    assert [c.sequence_number for c in r1.deliverable] == [1]


def test_out_of_order_chunks_are_buffered_then_delivered_in_order():
    buf = AudioOutputBuffer(utterance_id="u1")
    r_late = buf.push(_chunk(2))  # arrives before 0 and 1
    assert r_late.deliverable == []

    r0 = buf.push(_chunk(0))
    assert [c.sequence_number for c in r0.deliverable] == [0]

    r1 = buf.push(_chunk(1))
    # 1 arriving unlocks both 1 and the already-buffered 2, in order
    assert [c.sequence_number for c in r1.deliverable] == [1, 2]


def test_duplicate_chunk_is_dropped_never_played_twice():
    buf = AudioOutputBuffer(utterance_id="u1")
    buf.push(_chunk(0))
    r = buf.push(_chunk(0))
    assert r.deliverable == []
    assert r.dropped_duplicate == 1


def test_a_repeat_of_an_already_delivered_chunk_is_a_duplicate_not_stale():
    buf = AudioOutputBuffer(utterance_id="u1")
    buf.push(_chunk(0))
    buf.push(_chunk(1))
    r = buf.push(_chunk(0))  # arrives again, very late — already delivered, so classified as duplicate
    assert r.deliverable == []
    assert r.dropped_duplicate == 1


def test_permanently_missing_chunk_does_not_stall_playback_forever():
    buf = AudioOutputBuffer(utterance_id="u1", max_out_of_order_wait=3)
    # seq 0 never arrives. 1, 2, 3 pile up waiting for it.
    buf.push(_chunk(1))
    buf.push(_chunk(2))
    r = buf.push(_chunk(3))  # 3 pending items now >= max_out_of_order_wait
    assert r.missing_sequence_detected is True
    assert [c.sequence_number for c in r.deliverable] == [1, 2, 3]


def test_a_late_arrival_of_a_skipped_chunk_is_now_stale():
    buf = AudioOutputBuffer(utterance_id="u1", max_out_of_order_wait=2)
    buf.push(_chunk(1))
    r = buf.push(_chunk(2))  # triggers skip-ahead past missing seq 0
    assert r.missing_sequence_detected is True
    late = buf.push(_chunk(0))
    assert late.dropped_stale == 1


def test_cancel_drops_everything_and_ignores_further_pushes():
    buf = AudioOutputBuffer(utterance_id="u1")
    buf.push(_chunk(0))
    buf.cancel()
    assert buf.is_cancelled is True
    r = buf.push(_chunk(1))
    assert r.deliverable == []


def test_push_for_wrong_utterance_raises():
    buf = AudioOutputBuffer(utterance_id="u1")
    try:
        buf.push(_chunk(0, utterance_id="different"))
        assert False, "expected ValueError"
    except ValueError:
        pass
