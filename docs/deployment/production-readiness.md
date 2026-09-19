# Production readiness checklist

Status legend: **PASS** (verified this pass with real evidence) /
**FAIL** (verified broken) / **BLOCKED** (cannot be verified in this
environment) / **NOT VERIFIED** (real, attempted, inconclusive or needs
infrastructure this environment lacks).

- [x] **TLS** — NOT VERIFIED. No TLS termination exists in this build
  (local-dev HTTP/WS throughout). Architecture documented and ready to
  adopt with zero SDK code changes: `docs/deployment/tls.md`.
- [x] **DNS** — NOT APPLICABLE / NOT VERIFIED. No target deployment
  domain exists yet; nothing to configure or test.
- [x] **Firewall** — PARTIAL. Coturn's own relay-target denylist
  (RFC1918/loopback/link-local, SSRF-hardened) confirmed present and
  correct by reading `infrastructure/coturn/turnserver.conf`. No
  host/network-level firewall policy exists or was tested beyond the
  one-off iptables TURN experiment (fully reverted) in
  `docs/deployment/turn-verification.md`.
- [x] **Secrets** — PASS (design) / NOT VERIFIED (real KMS). Full repo +
  git history secret scan this pass: clean, no leaked credentials
  (`docs/security/README.md`). `MasterKeyProvider` abstraction
  implemented and unit-tested this pass
  (`docs/deployment/secrets-management.md`) so a real KMS/Vault backend
  is a one-line swap — but no real KMS/Vault was exercised (none
  available in this sandbox).
- [x] **KMS/Vault** — NOT VERIFIED. See above — abstraction ready, no
  real backend implemented or tested this pass by design (task
  instruction: don't implement three providers speculatively).
- [x] **PostgreSQL backups** — PASS, tested with real data this pass
  (`docs/deployment/database-redis-hardening.md`): real `pg_dump` →
  restore into a fresh DB → exact row-count and content match, 240
  tenants/480 users/173 sessions, zero errors.
- [x] **Redis** — PARTIAL PASS. Auth required (PASS), AOF persistence
  confirmed live (PASS), `maxmemory` unset (**real gap**, documented,
  not fixed this pass). See `docs/deployment/database-redis-hardening.md`.
- [x] **LiveKit** — PASS (functional, re-verified live this pass via
  restart test + real E2EE session immediately after). TLS/production
  networking (`use_external_ip`) NOT VERIFIED — local-dev config only.
- [x] **TURN** — NOT VERIFIED. Coturn is running, healthy, correctly
  hardened; a real forced-relay test was attempted this pass and was
  inconclusive (not a false pass — see `docs/deployment/
  turn-verification.md` for exactly why and what a conclusive test
  needs).
- [x] **API** — PASS. Stateless-by-design (re-confirmed this pass,
  `docs/deployment/multi-replica-readiness.md`), real HEALTHCHECK added
  and verified this pass (`docs/deployment/production-readiness.md`
  container section below), restart-tested live, all unit+integration
  tests passing (5 + 14), full live red-team pass found zero
  vulnerabilities in the attacks attempted (`docs/security/README.md`).
- [x] **AI Agent** — PARTIAL PASS. Lifecycle/authorization fully tested
  live (4/4 boundary tests), real-model pipeline round-trip tested with
  actual STT/translation/TTS inference (3/3 passing). **Multi-replica
  NOT SAFE today** — `AgentRegistry` is in-process; documented, not
  fixed this pass (real architecture decision deferred to an actual
  target deployment — see `docs/deployment/multi-replica-readiness.md`).
  **Safety validator gap: FIXED + VERIFIED** (was the single most
  important open AI-safety finding from the prior pass) — the
  deterministic validator now compares a normalized safety-entity object
  (numbers, dosage value+unit, frequency, duration value+unit, food
  constraints, negation, protected terms) instead of digits alone; unit
  swaps, negation flips, and medicine-name substitutions are all now
  rejected, verified by a 75-case test corpus plus real NLLB-200
  inference (`docs/ai/README.md`'s "Safety validator" section,
  `apps/ai-agent/tests/pipeline/test_safety_validator_corpus.py`). Stays
  fully deterministic — no model added to the validation path. Known
  remaining scope limit: English/Tamil only, Malayalam not yet covered.
- [x] **Monitoring** — PASS. Full metrics-coverage audit against the
  live Prometheus stack this pass (`docs/monitoring/README.md`) — every
  required category covered except GPU (N/A, no GPU in this build).
- [x] **Alerting** — NOT VERIFIED. No alert rules exist in this build
  (Prometheus/Grafana are deployed for dashboards/metrics storage, not
  alerting) — not found, not claimed, not addressed this pass (out of
  the audit's explicit scope; flagged here for completeness).
- [x] **Logging** — PASS. Structured JSON logs confirmed to never
  contain secrets/keys/tokens this pass (live red-team request/response
  inspection); Loki/Promtail pipeline confirmed running and scraping.
- [x] **Security** — PASS (this pass's own attacks) / gap found. Live
  red-team pass found zero successful attacks across auth, authz,
  tenant isolation, LiveKit token scoping, refresh-token replay, and
  internal service-secret endpoints (`docs/security/README.md`). Real
  dependency vulnerabilities found (`starlette` CVEs via the pinned
  `fastapi==0.115.6`) and documented, not mechanically patched given
  breaking-change risk — see the security scan results in the final
  report.
- [x] **Load testing** — PASS (executed, honestly scoped). 1/5/10/25
  concurrent real sessions tested; backend resource usage stayed low at
  every scale; the failures found at 10/25 are test-methodology
  artifacts (Chromium's fake-device concurrency limit, a per-IP rate
  limiter triggered by all synthetic traffic sharing one IP), not
  backend capacity limits. No capacity number is claimed — see
  `docs/deployment/load-testing.md` for exactly why and what a real test
  needs.
- [x] **E2EE** — PASS (Web↔Web), PASS (Web↔native/Python AI agent, fixed
  this pass — real encrypted audio verified crossing the platform
  boundary both directions), NOT DEVICE-VERIFIED (Flutter — fix applied
  by source-level reasoning, no Android emulator/device available in any
  sandbox pass to confirm it for real). Root cause was two concrete
  AyurEze implementation bugs (a key-derivation input mismatch and a
  key-size mismatch), not an upstream LiveKit limitation as previously
  classified — found by reading LiveKit's actual native crypto source.
  Classification: **D — application implementation bug, found and
  fixed** (`docs/e2ee/VALIDATION.md`'s "Fifth pass").
- [x] **Flutter validation** — BLOCKED (device/emulator tier). `flutter
  analyze`/`flutter test` re-verified for real this pass (0 issues,
  18/18) against a real Flutter SDK present in this session's
  environment. No Android SDK/emulator/device/KVM exists — real
  connect/publish/subscribe/E2EE testing on an actual device was not
  and could not be performed. Never claimed as verified.
- [x] **Web validation** — PASS. Full real-browser Playwright suite
  (12/13, the 1 expected E2EE failure), unit tests (19/19), typecheck
  and build clean.
- [x] **AI validation** — PASS (lifecycle/authorization/real-model
  pipeline), with the safety-validator gap noted above as the priority
  open item.
- [x] **Disaster recovery** — PASS (Postgres backup/restore, LiveKit/
  API/AI-agent restart, all tested live this pass) / DOCUMENTED ONLY
  (Redis full-loss drill, key-management failure, full VPS failure — see
  `docs/deployment/disaster-recovery.md` for exactly which is which and
  why).
- [x] **CI/CD** — PASS (written, locally-verified commands) / NOT
  VERIFIED (never executed end-to-end on GitHub's own runners from this
  sandbox — no CI execution capability exists here). `.github/workflows/
  ci.yml` and `security.yml` cover Go/Python/Web/Flutter checks, real
  integration tests, the full Playwright suite with the E2EE finding
  explicitly isolated as an expected-not-hidden blocker, dependency
  scanning (govulncheck/pip-audit/npm audit — all three run for real
  against this codebase this pass), secret scanning (gitleaks), SAST
  (CodeQL), and container scanning (Trivy) — the latter three need
  internet access this sandbox's egress policy blocks, so they run for
  the first time in CI, not proven here.

## Container hardening (real findings, this pass)

- Both Dockerfiles (`apps/api`, `apps/ai-agent`) run as non-root, use
  pinned (non-`latest`) base images.
- `apps/api`'s distroless image had **no HEALTHCHECK at all** (a real
  gap — distroless has no shell/curl) — fixed this pass with a tiny
  static Go binary, built and verified live (`docker inspect` reports
  `healthy`, real exit-code-0 execution against the live network) —
  verification image/container removed after confirming.
- `apps/ai-agent`'s Dockerfile already had a working curl-based
  HEALTHCHECK.
- No secrets baked into either image (env-var-only, confirmed by reading
  both Dockerfiles).
- Automated vulnerability scanning (Trivy) could not run in this sandbox
  (GitHub API/registry access blocked by org egress policy — not worked
  around) — wired into `.github/workflows/security.yml` instead, where
  GitHub-hosted runners have full internet access.
