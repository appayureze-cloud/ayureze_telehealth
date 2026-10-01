#!/usr/bin/env python3
"""Creates a LiveKit room DIRECTLY via LiveKit's own RoomService API (not
apps/api's Go session service), mints two raw access tokens via PyJWT
(not internal/token.Minter), and generates a random E2EE key locally (not
via internal/e2ee.KeyManager / Postgres envelope encryption). Prints JSON
with room/tokens/key so the minimal-repro test can drive both a native
participant and a raw livekit-client Web page with zero AyurEze code
involved anywhere in the chain. See docs/e2ee/VALIDATION.md.

Usage:
  minimal_repro_setup.py --livekit-url URL --api-key K --api-secret S
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import secrets
import sys
import time
import uuid

import jwt
from livekit import api


def mint(api_key: str, api_secret: str, room: str, identity: str, ttl_seconds: int = 600) -> str:
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


async def main_async(args: argparse.Namespace) -> None:
    room_name = f"minimal-repro-{uuid.uuid4().hex[:12]}"
    lkapi = api.LiveKitAPI(args.server_url, api_key=args.api_key, api_secret=args.api_secret)
    try:
        await lkapi.room.create_room(api.CreateRoomRequest(name=room_name, empty_timeout=60))
    finally:
        await lkapi.aclose()

    key_bytes = secrets.token_bytes(32)
    key_b64 = base64.b64encode(key_bytes).decode("ascii")

    native_token = mint(args.api_key, args.api_secret, room_name, "native-minimal")
    web_token = mint(args.api_key, args.api_secret, room_name, "web-minimal")

    print(json.dumps({
        "room": room_name,
        "key_b64": key_b64,
        "native_token": native_token,
        "web_token": web_token,
        "livekit_url": args.livekit_url,
    }))


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--livekit-url", required=True, help="ws(s):// URL for clients")
    p.add_argument("--server-url", required=False, help="http(s):// URL for RoomService (defaults to livekit-url with ws->http)")
    p.add_argument("--api-key", required=True)
    p.add_argument("--api-secret", required=True)
    args = p.parse_args()
    if not args.server_url:
        args.server_url = args.livekit_url.replace("wss://", "https://").replace("ws://", "http://")
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
