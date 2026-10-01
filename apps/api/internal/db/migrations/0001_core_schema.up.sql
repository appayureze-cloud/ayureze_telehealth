-- Core multi-tenant schema for the AyurEze Telehealth session platform.
-- Deliberately stores no medical conversation content — sessions/
-- participants/consents/events are metadata about calls, not their content.

CREATE TABLE tenants (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        CITEXT UNIQUE NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE users (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    email           CITEXT NOT NULL,
    password_hash   TEXT NOT NULL,
    role            TEXT NOT NULL CHECK (role IN ('patient', 'doctor', 'admin')),
    display_name    TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, email)
);
CREATE INDEX idx_users_tenant ON users(tenant_id);

-- A "session" is one telehealth consultation, mapped 1:1 to a LiveKit room.
CREATE TABLE sessions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    room_name       TEXT NOT NULL UNIQUE,
    status          TEXT NOT NULL CHECK (status IN ('created', 'active', 'ended')) DEFAULT 'created',
    created_by      UUID NOT NULL REFERENCES users(id),
    doctor_id       UUID NOT NULL REFERENCES users(id),
    patient_id      UUID NOT NULL REFERENCES users(id),
    ai_translation_authorized BOOLEAN NOT NULL DEFAULT false,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at      TIMESTAMPTZ,
    ended_at        TIMESTAMPTZ
);
CREATE INDEX idx_sessions_tenant ON sessions(tenant_id);
CREATE INDEX idx_sessions_doctor ON sessions(doctor_id);
CREATE INDEX idx_sessions_patient ON sessions(patient_id);

-- The authoritative list of who is allowed into a session's room. Row
-- existence here (not merely "has a valid token") is what join-session
-- authorization checks against; see internal/sessionsvc.
CREATE TABLE participants (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id      UUID NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    user_id         UUID REFERENCES users(id), -- null for the ai_agent role
    role            TEXT NOT NULL CHECK (role IN ('patient', 'doctor', 'ai_agent')),
    identity        TEXT NOT NULL, -- LiveKit participant identity
    status          TEXT NOT NULL CHECK (status IN ('authorized', 'joined', 'left', 'revoked')) DEFAULT 'authorized',
    joined_at       TIMESTAMPTZ,
    left_at         TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (session_id, identity)
);
CREATE INDEX idx_participants_session ON participants(session_id);

-- Consent to AI translation. Day 3 provides the schema/CRUD; Day 4 wires
-- enforcement (the AI agent may not join without a currently-granted row
-- here) and revocation handling.
CREATE TABLE consents (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id      UUID NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    subject         TEXT NOT NULL CHECK (subject IN ('ai_translation')),
    status          TEXT NOT NULL CHECK (status IN ('granted', 'revoked')),
    granted_by_user_id UUID NOT NULL REFERENCES users(id),
    granted_at      TIMESTAMPTZ,
    revoked_at      TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_consents_session ON consents(session_id);

-- Session timeline: room/participant lifecycle events, sourced from
-- internal actions and LiveKit webhooks. Never contains media/content.
CREATE TABLE session_events (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id      UUID NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    event_type      TEXT NOT NULL,
    payload         JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_session_events_session ON session_events(session_id);

-- Security/compliance audit trail: authn/authz decisions, admin actions.
CREATE TABLE audit_events (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID REFERENCES tenants(id) ON DELETE CASCADE,
    actor_user_id   UUID REFERENCES users(id),
    action          TEXT NOT NULL,
    resource_type   TEXT NOT NULL,
    resource_id     TEXT,
    outcome         TEXT NOT NULL CHECK (outcome IN ('success', 'denied', 'error')),
    metadata        JSONB NOT NULL DEFAULT '{}'::jsonb,
    ip_address      INET,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_audit_events_tenant ON audit_events(tenant_id);
CREATE INDEX idx_audit_events_actor ON audit_events(actor_user_id);
CREATE INDEX idx_audit_events_created_at ON audit_events(created_at);
