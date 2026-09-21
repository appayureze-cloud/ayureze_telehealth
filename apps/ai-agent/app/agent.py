"""The AI agent's real LiveKit connection lifecycle.

Flow (see lifecycle.py for the enforced state machine):
  authorize (Go API, consent-gated) -> join encrypted room -> subscribe to
  authorized media -> [Day 6: process/translate/publish] -> leave, whether
  by explicit stop, session end, or consent revocation (LiveKit
  force-disconnects us with DisconnectReason.PARTICIPANT_REMOVED).

The agent never joins a room "because it exists" — it only ever connects
after this module's authorize() call succeeds, which itself only succeeds
when the Go API finds an active ai_translation consent for this exact
session (internal/sessionsvc.AuthorizeAIAgent on the Go side).
"""

from __future__ import annotations

import asyncio
import logging

from livekit import rtc

from .api_client import APIClient, AuthorizationDenied
from .lifecycle import AgentState, InvalidTransition, LifecycleTracker
from .logging_setup import log
from .metrics import (
    AI_AGENT_AUTHORIZE_TOTAL,
    AI_AGENT_JOIN_TOTAL,
    AI_AGENT_STATE_TRANSITIONS_TOTAL,
)
from .pipeline.orchestrator import TranslationPipeline
from .pipeline.streaming import LiveAudioProcessor

PARTICIPANT_REMOVED = 4  # rtc.DisconnectReason.PARTICIPANT_REMOVED


class AIAgent:
    def __init__(
        self,
        session_id: str,
        tenant_id: str,
        livekit_url: str,
        api_client: APIClient,
        logger: logging.Logger,
        pipeline: TranslationPipeline | None = None,
    ):
        self.session_id = session_id
        self.tenant_id = tenant_id
        self._livekit_url = livekit_url
        self._api_client = api_client
        self._logger = logger
        self._pipeline = pipeline
        self.lifecycle = LifecycleTracker(session_id=session_id)
        self._room: rtc.Room | None = None
        self._audio_processor: LiveAudioProcessor | None = None
        self._disconnected_event = asyncio.Event()
        self._stop_requested = False

    def _transition(self, target: AgentState, detail: str | None = None) -> None:
        try:
            self.lifecycle.transition(target, detail=detail)
        except InvalidTransition:
            # Already terminal (e.g. two disconnect signals racing) — not
            # an error worth surfacing, just a no-op.
            return
        AI_AGENT_STATE_TRANSITIONS_TOTAL.labels(state=target.value).inc()
        log(
            self._logger,
            logging.INFO,
            "ai_agent_state_transition",
            event_type="ai_agent_state_transition",
            session_id=self.session_id,
            state=target.value,
            detail=detail,
        )

    async def run(self) -> None:
        """Runs the full lifecycle to completion (a terminal state). Safe
        to await from a background task; call stop() from another
        coroutine to end it early."""
        try:
            grant = await self._authorize()
            AI_AGENT_AUTHORIZE_TOTAL.labels(outcome="success").inc()
            await self._join(grant)
            AI_AGENT_JOIN_TOTAL.labels(outcome="success").inc()
        except AuthorizationDenied as e:
            AI_AGENT_AUTHORIZE_TOTAL.labels(outcome="denied").inc()
            self._transition(AgentState.FAILED, detail=f"authorization_denied:{e.status_code}")
            return
        except Exception as e:  # noqa: BLE001 - any join failure must land in FAILED, not crash silently
            AI_AGENT_JOIN_TOTAL.labels(outcome="error").inc()
            log(
                self._logger,
                logging.ERROR,
                "ai_agent_join_failed",
                event_type="ai_agent_join_failed",
                session_id=self.session_id,
                error=str(e),
            )
            self._transition(AgentState.FAILED, detail="join_error")
            return

        await self._disconnected_event.wait()

    async def _authorize(self):
        self._transition(AgentState.AUTHORIZED, detail=None)
        # REQUESTED -> AUTHORIZED is a single call in this implementation
        # (the Go API's consent check *is* the authorization step) — there
        # is no separate "authorized but not yet confirmed" state to model
        # here, unlike a multi-step human OAuth-style flow.
        grant = await self._api_client.authorize_ai_agent(self.tenant_id, self.session_id)
        return grant

    async def _join(self, grant) -> None:
        self._transition(AgentState.JOINING)

        # IMPORTANT: do NOT base64-decode grant.e2ee_key before handing it
        # to KeyProviderOptions. The Web SDK's ExternalE2EEKeyProvider.setKey()
        # is fed this same base64 *text* verbatim and UTF-8-encodes it before
        # running PBKDF2 (salt "LKFrameEncryptionKey", 100000 iterations,
        # SHA-256 — LiveKit's own documented cross-SDK-compatible path). The
        # native KeyProvider's shared_key runs through the identical default
        # PBKDF2/salt, so it must receive the identical input bytes: the
        # UTF-8 encoding of the base64 text itself, not the decoded raw key.
        # Decoding first derives a completely different, unrelated key and
        # silently breaks cross-platform decryption (see
        # docs/e2ee/VALIDATION.md's key-derivation-input finding).
        key_bytes = grant.e2ee_key.encode("utf-8")
        e2ee_options = rtc.E2EEOptions(
            key_provider_options=rtc.KeyProviderOptions(shared_key=key_bytes),
        )
        room = rtc.Room()
        self._room = room

        room.on("track_subscribed", self._on_track_subscribed)
        room.on("disconnected", self._on_disconnected)
        room.on("e2ee_state_changed", self._on_e2ee_state_changed)

        await room.connect(
            self._livekit_url,
            grant.access_token,
            options=rtc.RoomOptions(auto_subscribe=True, e2ee=e2ee_options),
        )
        self._transition(AgentState.CONNECTED, detail=f"identity={grant.identity}")

    def _on_e2ee_state_changed(self, participant, state) -> None:
        # Safe to log as-is: LiveKit's E2EEState is a small enum (kNew/
        # kOk/kKeyRatcheted/kMissingKey/kEncryptionFailed/
        # kDecryptionFailed/kInternalError, matching sdk/flutter's
        # AyurezeE2EEState mapping) — never a key, token, or media
        # payload. This was previously unobserved: a failure here (e.g.
        # a real per-participant decryption error) would otherwise be
        # silently indistinguishable from "no audio published yet".
        log(
            self._logger,
            logging.INFO,
            "ai_agent_e2ee_state_changed",
            event_type="ai_agent_e2ee_state_changed",
            session_id=self.session_id,
            participant=participant.identity,
            state=str(state),
        )

    def _on_track_subscribed(self, track, publication, participant) -> None:
        if track.kind != rtc.TrackKind.KIND_AUDIO:
            return
        # Reached once real decrypted audio frames are flowing from an
        # authorized remote participant — proves the encrypted media path
        # itself works even with no pipeline configured (Day 5).
        self._transition(AgentState.PROCESSING, detail=f"audio_track_from={participant.identity}")

        if self._pipeline is None or self._room is None:
            return  # no ML pipeline wired in — state machine only (Day 5 mode)

        if self._audio_processor is None:
            self._audio_processor = LiveAudioProcessor(
                room=self._room,
                pipeline=self._pipeline,
                logger=self._logger,
                session_id=self.session_id,
                on_publish_start=lambda: self._transition(AgentState.PUBLISHING),
                on_publish_end=lambda: self._transition(AgentState.PROCESSING),
            )
        asyncio.create_task(self._audio_processor.handle_track(track, participant))

    def _on_disconnected(self, reason) -> None:
        if reason == PARTICIPANT_REMOVED:
            self._transition(AgentState.REVOKED, detail="participant_removed")
        else:
            self._transition(AgentState.DISCONNECTED, detail=str(reason))
        self._disconnected_event.set()

    async def stop(self) -> None:
        self._stop_requested = True
        if self._audio_processor is not None:
            await self._audio_processor.stop()
        if self._room is not None and self._room.isconnected:
            await self._room.disconnect()
        # disconnect() triggers the "disconnected" event above (reason
        # CLIENT_INITIATED), which sets _disconnected_event and performs
        # the state transition — no need to duplicate that here.
