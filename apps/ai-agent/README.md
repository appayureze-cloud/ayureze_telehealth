# apps/ai-agent

Python AI Translation Agent for AyurEze Telehealth.

**Day 5** built the agent's real connection lifecycle: it authenticates to
the Go API as a trusted backend service, is authorized only when
AI-translation consent is currently active, joins the LiveKit room as a
genuine **encrypted** participant (real SFrame E2EE using the session key
handed over by the Go API — not a simulation), subscribes to media, and is
force-disconnected the moment consent is revoked.

**Day 6** (current) wires in the real VAD → STT → language ID →
terminology → translation → safety validation → TTS pipeline
(`app/pipeline/`) against genuine open-source models (Silero VAD,
faster-whisper, NLLB-200, MMS-TTS — see `docs/ai/README.md` for the
provider interfaces and the documented IndicTrans2 substitution
rationale), gated behind `AI_AGENT_ENABLE_PIPELINE` so Day 5's
lifecycle-only behavior remains the default and lifecycle tests stay fast.

## Modules

| File | Responsibility |
|---|---|
| `app/lifecycle.py` | The enforced state machine (`REQUESTED → AUTHORIZED → JOINING → CONNECTED → PROCESSING → PUBLISHING`, with `REVOKED`/`DISCONNECTED`/`FAILED` as terminal states) |
| `app/api_client.py` | Calls the Go API's `POST /internal/ai-agent/sessions/{id}/authorize` — the only source of LiveKit tokens/E2EE keys; the agent never mints its own credentials |
| `app/agent.py` | Connects to LiveKit with the session's real E2EE key, drives lifecycle transitions off real LiveKit events (`track_subscribed`, `disconnected` incl. distinguishing `PARTICIPANT_REMOVED` → `REVOKED`) |
| `app/registry.py` | In-memory active-agent-instances registry (one process; sharding across replicas by session_id is a future scaling step) |
| `app/main.py` | FastAPI control surface: start/stop/status + health/ready/metrics |
| `app/pipeline/vad.py` | Silero VAD (ONNX, no torch) + turn segmentation with hangover/min-duration filtering |
| `app/pipeline/stt.py` | faster-whisper speech-to-text |
| `app/pipeline/lid.py` | Text-based language ID, cross-checked against STT's audio-based guess |
| `app/pipeline/terminology.py` | Extracts numbers/dosage/frequency/duration/glossary spans from the source text before translation |
| `app/pipeline/translation.py` | NLLB-200 translation (documented substitute for the spec's IndicTrans2 pick — see `docs/ai/README.md`) |
| `app/pipeline/safety.py` | Deterministic validator: blocks publication if numbers changed between source and translation |
| `app/pipeline/tts.py` | MMS-TTS (VITS) speech synthesis |
| `app/pipeline/orchestrator.py` | Ties the above together with per-stage latency measurement |
| `app/pipeline/streaming.py` | Wires a live LiveKit audio track through VAD → orchestrator → translated-audio republish + data-channel captions, with barge-in cancellation |

## Run locally

```bash
../../scripts/dev-up.sh
../../scripts/db-seed.sh
../../scripts/run-api.sh &

python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Day 6 pipeline (optional — skip for Day 5 lifecycle-only mode):
pip install -r requirements-pipeline.txt --index-url https://download.pytorch.org/whl/cpu --extra-index-url https://pypi.org/simple
./scripts/download_models.sh   # ~2.5GB, one-time

set -a && source ../../.env && set +a
export LIVEKIT_URL=ws://localhost:7880
export API_BASE_URL=http://localhost:8080
export AI_AGENT_ENABLE_PIPELINE=true   # omit for Day 5 lifecycle-only mode
uvicorn app.main:app --port 8090
```

Trigger a join (after granting AI-translation consent for a session via
the Go API):

```bash
curl -X POST http://localhost:8090/v1/agent/sessions/<session_id>/start \
  -H 'Content-Type: application/json' -d '{"tenant_id":"<tenant_id>"}'

curl http://localhost:8090/v1/agent/sessions/<session_id>   # poll state
```

## Tests

```bash
pytest                              # fast: lifecycle state machine, VAD, terminology, safety — no external deps
pytest -m models -v tests/pipeline/test_pipeline_models.py   # real STT/translation/TTS models, no LiveKit needed
pytest -m integration -v tests/test_agent_integration.py           # Day 5: real stack, pipeline disabled, no mocks
pytest -m integration -v tests/test_pipeline_live_integration.py   # Day 6: real stack, pipeline enabled, no mocks
```

`test_agent_integration.py` connects a second real LiveKit participant
(standing in for the doctor's browser) that publishes a synthetic audio
track encrypted with the session's actual E2EE key, then drives the real
agent through authorize → join → `CONNECTED` → `PROCESSING` (on receiving
that track) → consent revoked → `REVOKED` (force-disconnected by LiveKit).

`test_pipeline_live_integration.py` goes further: it synthesizes real
English speech via TTS (standing in for a doctor's microphone), streams it
into a live encrypted LiveKit room at real-time pace, and verifies the
agent's VAD detects the turn, runs the full STT → language ID →
terminology → translation → safety validation → TTS pipeline, publishes a
`PUBLISHING` state transition, and delivers a caption data message with
the transcript, translated text, and per-stage latency — the complete
Day 6 chain, against real cryptography, real WebRTC, and real ML models,
not mocks.

`test_pipeline_models.py::test_safety_validator_blocks_a_corrupted_translation`
verifies the one failure mode most worth being paranoid about: a
translation that silently drops a number never gets published as audio.
