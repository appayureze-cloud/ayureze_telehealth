#!/usr/bin/env python3
"""Runs native_participant.py's run_participant() directly with a token and
E2EE key supplied by the caller — bypassing main_async() entirely, so no Go
API call, no login, no session/consent logic is involved. Used only for the
"minimal reproduction, independent of AyurEze business logic" experiment
(docs/e2ee/VALIDATION.md).

Usage:
  minimal_native_runner.py --livekit-url URL --token JWT --key-b64 B64 \
      --duration-seconds 12 [--publish-audio] [--json]
"""
from __future__ import annotations

import argparse
import asyncio
import sys

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from native_participant import run_participant, emit  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--livekit-url", required=True)
    p.add_argument("--token", required=True)
    p.add_argument("--key-b64", required=True)
    p.add_argument("--duration-seconds", type=float, default=12.0)
    p.add_argument("--publish-audio", action="store_true")
    args = p.parse_args()
    try:
        asyncio.run(
            run_participant(
                args.livekit_url,
                args.token,
                args.key_b64,
                args.duration_seconds,
                args.publish_audio,
                ready_extra={},
            )
        )
    except Exception as e:  # noqa: BLE001
        emit({"event": "error", "error": str(e)})
        sys.exit(1)


if __name__ == "__main__":
    main()
