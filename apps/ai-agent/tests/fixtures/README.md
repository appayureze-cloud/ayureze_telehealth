# Test fixtures

## `jfk.flac`

A ~11-second excerpt of President John F. Kennedy's January 20, 1961
inaugural address ("...ask not what your country can do for you...").
Used as a real, non-synthetic "microphone" input for tests that need
genuine human speech (with natural pauses, prosody, and breath sounds) —
notably `tests/test_pipeline_live_integration.py`, which needs VAD to
actually detect speech, something no synthetic TTS output reliably does
for this build's Silero VAD model (see `docs/ai/README.md`'s "Known
limitations" for the root-caused, now-fixed `vad.py` context-buffer bug
this surfaced).

**Provenance**: copied unmodified from [openai/whisper](https://github.com/openai/whisper)'s
own test suite (`tests/jfk.flac`), an MIT-licensed repository. The
recording itself is a U.S. government work (a presidential address) and
is in the public domain. It is used across many open-source speech
projects as a standard "real speech" test sample for exactly this
reason. No patient data, no synthetic/fabricated content — real,
legitimately-sourced audio only.
