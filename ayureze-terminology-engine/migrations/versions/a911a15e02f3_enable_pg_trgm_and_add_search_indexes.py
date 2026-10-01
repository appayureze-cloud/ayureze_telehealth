"""enable pg_trgm and add search indexes

Revision ID: a911a15e02f3
Revises: 9e1282b09052
Create Date: 2026-09-26 03:01:32.560347

"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = 'a911a15e02f3'
down_revision: str | None = '9e1282b09052'
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    # pg_trgm: trigram similarity for fuzzy matching (spec section 14) —
    # ships with stock postgres:16 images, no custom image needed (see
    # docs/ARCHITECTURE.md).
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    op.execute(
        "CREATE INDEX ix_concept_names_normalized_name_trgm "
        "ON concept_names USING gin (normalized_name gin_trgm_ops)"
    )

    # PostgreSQL full-text search: a generated tsvector column over the
    # ORIGINAL name (not normalized_name) so language-appropriate stemming
    # applies to real words, with a GIN index. 'simple' config deliberately
    # — this corpus mixes English, Sanskrit transliteration, and Sanskrit
    # script; English-specific stemming ('english' config) would silently
    # mangle the non-English majority of names, which is worse than no
    # stemming at all for a terminology lookup tool.
    op.execute(
        "ALTER TABLE concept_names ADD COLUMN name_tsv tsvector "
        "GENERATED ALWAYS AS (to_tsvector('simple', name)) STORED"
    )
    op.execute("CREATE INDEX ix_concept_names_name_tsv ON concept_names USING gin (name_tsv)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_concept_names_name_tsv")
    op.execute("ALTER TABLE concept_names DROP COLUMN IF EXISTS name_tsv")
    op.execute("DROP INDEX IF EXISTS ix_concept_names_normalized_name_trgm")
    op.execute("DROP EXTENSION IF EXISTS pg_trgm")
