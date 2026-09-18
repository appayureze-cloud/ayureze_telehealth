# apps/ai-agent

Python AI Translation Agent for AyurEze Telehealth.

**Day 5 scope** (current): the agent's real connection lifecycle — it
authenticates to the Go API as a trusted backend service, is authorized
only when AI-translation consent is currently active for the session,
joins the LiveKit room as a genuine **encrypted** participant (real SFrame
E2EE using the session key handed over by the Go API — not a simulation),
subscribes to media, and is force-disconnected the moment consent is
revoked. The actual VAD/STT/translation/TTS pipeline is Day 6 scope — see
`docs/ai/README.md`.

## Modules

| File | Responsibility |
|---|---|
| `app/lifecycle.py` | The enforced state machine (`REQUESTED → AUTHORIZED → JOINING → CONNECTED → PROCESSING → PUBLISHING`, with `REVOKED`/`DISCONNECTED`/`FAILED` as terminal states) |
| `app/api_client.py` | Calls the Go API's `POST /internal/ai-agent/sessions/{id}/authorize` — the only source of LiveKit tokens/E2EE keys; the agent never mints its own credentials |
| `app/agent.py` | Connects to LiveKit with the session's real E2EE key, drives lifecycle transitions off real LiveKit events (`track_subscribed`, `disconnected` incl. distinguishing `PARTICIPANT_REMOVED` → `REVOKED`) |
| `app/registry.py` | In-memory active-agent-instances registry (one process; sharding across replicas by session_id is a future scaling step) |
| `app/main.py` | FastAPI control surface: start/stop/status + health/ready/metrics |

## Run locally

```bash
../../scripts/dev-up.sh
../../scripts/db-seed.sh
../../scripts/run-api.sh &

python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

set -a && source ../../.env && set +a
export LIVEKIT_URL=ws://localhost:7880
export API_BASE_URL=http://localhost:8080
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
pytest                                    # unit tests (lifecycle state machine) — no external deps
pytest -m integration -v tests/test_agent_integration.py   # real stack, no mocks (see file docstring)
```

The integration test connects a second real LiveKit participant (standing
in for the doctor's browser) that publishes a synthetic audio track
encrypted with the session's actual E2EE key, then drives the real agent
through authorize → join → `CONNECTED` → `PROCESSING` (on receiving that
track) → consent revoked → `REVOKED` (force-disconnected by LiveKit) — the
full security-relevant lifecycle, against real cryptography and real
WebRTC, not mocks.
