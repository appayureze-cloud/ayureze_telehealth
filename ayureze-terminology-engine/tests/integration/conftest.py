"""Integration test fixtures — require a REAL Postgres database (spec
section 21's "database migrations" tests included). Uses a dedicated
`ayureze_terminology_test` database, never the dev database
`ayureze_terminology` these tests could otherwise silently pollute.

Run with: docker compose up -d postgres (or point TERMINOLOGY_TEST_DATABASE_URL
at any real Postgres 16+ with pg_trgm available), then pytest -m integration.
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from models import Base

TEST_DATABASE_URL = os.environ.get(
    "TERMINOLOGY_TEST_DATABASE_URL",
    "postgresql+psycopg://terminology:{password}@localhost:5433/ayureze_terminology_test".format(
        password=os.environ.get("TERMINOLOGY_POSTGRES_PASSWORD", "terminology")
    ),
)


@pytest.fixture(scope="session")
def engine():
    eng = create_engine(TEST_DATABASE_URL)
    Base.metadata.drop_all(eng)
    Base.metadata.create_all(eng)
    with eng.connect() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_concept_names_normalized_name_trgm ON concept_names USING gin (normalized_name gin_trgm_ops)"))
        conn.commit()
    yield eng
    eng.dispose()


@pytest.fixture()
def db(engine):
    """One test = one outer transaction, always rolled back at teardown —
    tests never see each other's data and never require manual cleanup.

    Ingestion/deduplication code under test calls session.commit()
    internally (real production behavior, not something tests should have
    to special-case). A plain "begin a transaction, roll it back" pattern
    breaks the moment that happens: commit() ends the outer transaction
    early, so the fixture's own rollback() has nothing left to undo and
    the test's writes leak into the real test database (confirmed
    experimentally: SAWarning "transaction already deassociated from
    connection" on every test that hit a commit() path). Fixed with
    SQLAlchemy's own documented recipe for this exact situation: run
    everything inside a SAVEPOINT, and transparently restart a new
    SAVEPOINT via the after_transaction_end event whenever the inner
    session's commit() ends the current one — the OUTER transaction (never
    committed by application code) is what the fixture finally rolls back.
    """
    connection = engine.connect()
    outer_transaction = connection.begin()
    Session = sessionmaker(bind=connection, join_transaction_mode="create_savepoint")
    session = Session()

    try:
        yield session
    finally:
        session.close()
        outer_transaction.rollback()
        connection.close()
