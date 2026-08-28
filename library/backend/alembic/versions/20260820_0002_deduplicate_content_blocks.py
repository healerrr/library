"""deduplicate content blocks per site

Revision ID: 20260820_0002
Revises: 20260820_0001
Create Date: 2026-08-20
"""

from alembic import op


revision = "20260820_0002"
down_revision = "20260820_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "DELETE FROM content_blocks AS duplicate "
        "USING content_blocks AS original "
        "WHERE duplicate.site_id = original.site_id "
        "AND duplicate.content_hash = original.content_hash "
        "AND duplicate.id > original.id"
    )
    op.create_index(
        "uq_content_blocks_site_hash",
        "content_blocks",
        ["site_id", "content_hash"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_content_blocks_site_hash", table_name="content_blocks")
