-- Per-session E2EE key material. The raw key is NEVER stored — only its
-- envelope-encrypted form (AES-256-GCM under API_E2EE_MASTER_KEY_HEX; see
-- internal/e2ee). This lets the API hand the key to newly-authorized
-- participants on join without keeping plaintext key material at rest.
ALTER TABLE sessions
    ADD COLUMN e2ee_key_encrypted BYTEA NOT NULL DEFAULT '\x'::bytea;
