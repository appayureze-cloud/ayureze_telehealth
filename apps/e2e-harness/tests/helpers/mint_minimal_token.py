#!/usr/bin/env python3
"""Mint a raw LiveKit access token directly against LIVEKIT_API_KEY/SECRET,
using nothing but PyJWT and LiveKit's public, documented JWT claim spec
(https://docs.livekit.io/home/get-started/authentication/). Deliberately
does NOT call the Go API, does NOT touch internal/token.Minter, does NOT
touch Postgres/Redis/consent/tenant logic — used only for the standalone
"minimal reproduction, independent of AyurEze business logic" experiment
in docs/e2ee/VALIDATION.md. Never used in production.

Usage:
  mint_minimal_token.py --api-key K --api-secret S --room R --identity I [--ttl-seconds 600]
Prints the raw JWT to stdout.
"""
from __future__ import annotations

import argparse
import time

import jwt


def mint(api_key: str, api_secret: str, room: str, identity: str, ttl_seconds: int) -> str:
    now = int(time.time())
    payload = {
        "iss": api_key,
        "sub": identity,
        "jti": identity,
        "nbf": now,
        "exp": now + ttl_seconds,
        "video": {
            "room": room,
            "roomJoin": True,
            "canPublish": True,
            "canSubscribe": True,
            "canPublishData": True,
        },
    }
    return jwt.encode(payload, api_secret, algorithm="HS256")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--api-key", required=True)
    p.add_argument("--api-secret", required=True)
    p.add_argument("--room", required=True)
    p.add_argument("--identity", required=True)
    p.add_argument("--ttl-seconds", type=int, default=600)
    args = p.parse_args()
    print(mint(args.api_key, args.api_secret, args.room, args.identity, args.ttl_seconds))


if __name__ == "__main__":
    main()
