"""WHO ICD-11 API adapter — CC-BY-ND-3.0-IGO (verified 2026-09-26, see
docs/LICENSE_MATRIX.md). Commercial lookup/display use is permitted; this
adapter only ever performs a LIVE search against WHO's own API and returns
codes/titles verbatim (never altered — the license's "No-Derivatives"
condition). It does NOT compile or cache a bulk NAMASTE<->ICD-11 mapping
table locally: WHO's own license text states that publishing such a
crosswalk needs a SEPARATE WRITTEN AGREEMENT beyond the base API terms
(see docs/LICENSE_MATRIX.md's "who_icd11_tm2" entry) — this adapter's
live, on-demand, per-query lookups don't need that agreement; compiling
and shipping a static mapping table would.

Requires free OAuth2 client-credentials registered at
https://icd.who.int/icdapi — not configured in this environment (no
client ID/secret set), so lookup() raises AdapterNotConfiguredError here,
honestly, rather than faking a response.
"""

from __future__ import annotations

import os
import time

import httpx

from .base import AdapterNotConfiguredError, BiomedicalAdapter, BiomedicalLookupResult

_TOKEN_URL = "https://icdaccessmanagement.who.int/connect/token"
_SEARCH_URL = "https://id.who.int/icd/entity/search"


class ICD11Adapter(BiomedicalAdapter):
    def __init__(self, client_id: str | None = None, client_secret: str | None = None) -> None:
        self._client_id = client_id or os.environ.get("TERMINOLOGY_ICD11_CLIENT_ID")
        self._client_secret = client_secret or os.environ.get("TERMINOLOGY_ICD11_CLIENT_SECRET")
        self._token: str | None = None
        self._token_expires_at: float = 0.0

    def _ensure_token(self) -> str:
        if not self._client_id or not self._client_secret:
            raise AdapterNotConfiguredError(
                "ICD-11 adapter requires TERMINOLOGY_ICD11_CLIENT_ID/TERMINOLOGY_ICD11_CLIENT_SECRET "
                "(free registration at https://icd.who.int/icdapi) — not configured in this environment."
            )
        if self._token and time.monotonic() < self._token_expires_at:
            return self._token
        response = httpx.post(
            _TOKEN_URL,
            data={
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "scope": "icdapi_access",
                "grant_type": "client_credentials",
            },
            timeout=10.0,
        )
        response.raise_for_status()
        payload = response.json()
        self._token = payload["access_token"]
        self._token_expires_at = time.monotonic() + payload.get("expires_in", 3600) - 60
        return self._token

    def lookup(self, term: str) -> list[BiomedicalLookupResult]:
        token = self._ensure_token()
        response = httpx.get(
            _SEARCH_URL,
            params={"q": term},
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
                "Accept-Language": "en",
                "API-Version": "v2",
            },
            timeout=10.0,
        )
        response.raise_for_status()
        payload = response.json()
        results = []
        for entity in payload.get("destinationEntities", []):
            results.append(BiomedicalLookupResult(
                code=entity.get("theCode", ""),
                display=entity.get("title", "").replace("<em class='found'>", "").replace("</em>", ""),
                source="ICD-11",
                source_url=entity.get("id", _SEARCH_URL),
            ))
        return results
