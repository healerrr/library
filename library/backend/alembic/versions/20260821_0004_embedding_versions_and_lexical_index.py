"""add embedding versions and lexical candidate index

Revision ID: 20260821_0004
Revises: 20260821_0003
"""

from alembic import op
import sqlalchemy as sa


revision = "20260821_0004"
down_revision = "20260821_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.add_column(
        "content_blocks",
        sa.Column("embedding_version", sa.String(255), nullable=False, server_default="unknown"),
    )
    op.create_index(
        "ix_content_blocks_embedding_version",
        "content_blocks",
        ["embedding_version"],
    )
    op.execute(
        "CREATE INDEX ix_content_blocks_normalized_trgm "
        "ON content_blocks USING gin (normalized_content gin_trgm_ops)"
    )


def downgrade() -> None:
    op.drop_index("ix_content_blocks_normalized_trgm", table_name="content_blocks")
    op.drop_index("ix_content_blocks_embedding_version", table_name="content_blocks")
    op.drop_column("content_blocks", "embedding_version")
