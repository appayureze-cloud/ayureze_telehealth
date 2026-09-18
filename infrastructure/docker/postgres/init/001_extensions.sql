-- AyurEze Telehealth — baseline Postgres extensions
-- Full domain schema (tenants/users/sessions/participants/consents/...)
-- is created by versioned migrations under apps/api/internal/db/migrations
-- (introduced on Day 3). This init script only prepares the database for
-- those migrations to run against.

CREATE EXTENSION IF NOT EXISTS "pgcrypto";   -- gen_random_uuid()
CREATE EXTENSION IF NOT EXISTS "citext";     -- case-insensitive emails
