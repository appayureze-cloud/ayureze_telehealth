# Security

Spec section 23's checklist, with what's actually implemented (and
verified with real requests, not just written) vs. what's a known gap.

| Requirement | Status | How |
|---|---|---|
| Validate all API input | ✅ | Pydantic v2 schemas on every request body (`schemas/terminology.py`); `q`/`text` length-bounded |
| Limit query lengths | ✅ verified | `TERMINOLOGY_MAX_QUERY_LENGTH` (default 200); a real 300-char query returns `422` — see `docs/API.md` |
| Prevent SQL injection | ✅ verified | Every query in `terminology/search.py` and `deduplication/pipeline.py` uses SQLAlchemy `text()` with bound parameters, never string formatting; a real `'; DROP TABLE concepts;--` payload returns `200` with the string treated as literal text, table intact |
| Use parameterized queries | ✅ | Same as above — grep-verified zero f-string/`.format()`-built SQL |
| Avoid arbitrary file access | ✅ | No API endpoint accepts a file path or reads from user-supplied paths; ingestion scripts read fixed, hardcoded paths under `data/raw/` only |
| Avoid arbitrary URL fetching from API requests | ✅ | No endpoint accepts a URL parameter that triggers a server-side fetch; the only outbound HTTP calls are `mappings/*.py`'s adapters, called from ingestion/library code, never from an unauthenticated API request path |
| Never execute source data | ✅ | Ingested content is only ever displayed as text or JSON-serialized (`original_payload`); no `eval`/`exec`/template-injection path exists anywhere in `ingestion/` or `api/` |
| Never expose database credentials | ✅ | `TERMINOLOGY_DATABASE_URL` is env-var only, never returned by any endpoint or logged (`api/main.py`'s exception handler returns a generic `"internal server error"`, never exception details) |
| Never expose raw secrets | ✅ | Same as above; `.env` is gitignored (inherits the root repo's `.gitignore` pattern) |
| Use environment variables for credentials | ✅ | `config/settings.py` (`pydantic-settings`), all adapter credentials in `mappings/*.py` |
| Basic request rate limiting | ✅ implemented, ⚠️ known limitation | `api/rate_limit.py`, in-memory per-IP sliding window, default 120 req/min. **Known limitation**: in-process only — a multi-replica deployment needs a shared store (Redis) instead; not implemented in Phase 1 per the "don't add Redis without a demonstrated need" decision (see `docs/ARCHITECTURE.md`) |

## What this service does NOT do (by design, not oversight)

- No authentication/authorization layer — Phase 1 is a standalone
  reference lookup service with no patient data, no PII, and (per the
  task's own explicit scope) no connection to the AI pipeline or patient/
  doctor applications. Adding auth before this is wired into a real
  product consuming patient context is a next-phase decision, not
  something to bolt on speculatively now.
- No TLS termination in `docker-compose.yml` — expected to sit behind a
  real reverse proxy/load balancer in any actual deployment, matching how
  the existing telehealth stack's own services are fronted.
- No secrets manager integration (Vault, AWS Secrets Manager, etc.) —
  plain environment variables, appropriate for this phase's standalone,
  non-production-traffic scope; the existing telehealth repo's own
  production services follow the same plain-env-var pattern currently.

## Adapter security (spec sections 18–19)

Every `mappings/*.py` adapter (`ICD11Adapter`, `SnomedAdapter`,
`RxNormAdapter`, `MeshAdapter`, `LoincAdapter`, `AtcAdapter`) only makes
OUTBOUND requests to a fixed, hardcoded, well-known API host — never a
user-supplied URL — closing off SSRF as an attack surface through this
codebase's own adapter layer. `SnomedAdapter`'s server URL IS configurable
(`TERMINOLOGY_SNOMED_SERVER_URL`), but that's an operator-set deployment
config value, not something any API request can influence.
