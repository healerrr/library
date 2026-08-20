"""create initial copyguard schema"""

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

revision = "20260820_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "sites",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("domain", sa.String(255), nullable=False, unique=True),
        sa.Column("sitemap_url", sa.String(2048), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        sa.Column("last_crawled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_sites_status", "sites", ["status"])

    op.create_table(
        "pages",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("site_id", sa.BigInteger(), sa.ForeignKey("sites.id", ondelete="CASCADE"), nullable=False),
        sa.Column("url", sa.String(2048), nullable=False),
        sa.Column("title", sa.String(500), nullable=True),
        sa.Column("meta_description", sa.Text(), nullable=True),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("content_hash", sa.String(64), nullable=True),
        sa.Column("crawled_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("site_id", "url", name="uq_pages_site_url"),
    )
    op.create_index("ix_pages_site_id", "pages", ["site_id"])

    op.create_table(
        "content_blocks",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("site_id", sa.BigInteger(), sa.ForeignKey("sites.id", ondelete="CASCADE"), nullable=False),
        sa.Column("page_id", sa.BigInteger(), sa.ForeignKey("pages.id", ondelete="CASCADE"), nullable=False),
        sa.Column("page_title", sa.String(500), nullable=True),
        sa.Column("url", sa.String(2048), nullable=False),
        sa.Column("content_type", sa.String(32), nullable=False),
        sa.Column("original_content", sa.Text(), nullable=False),
        sa.Column("normalized_content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("embedding", Vector(512), nullable=False),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_content_blocks_site_id", "content_blocks", ["site_id"])
    op.create_index("ix_content_blocks_page_id", "content_blocks", ["page_id"])
    op.create_index("ix_content_blocks_hash", "content_blocks", ["content_hash"])
    op.execute(
        "CREATE INDEX ix_content_blocks_embedding_hnsw "
        "ON content_blocks USING hnsw (embedding vector_cosine_ops)"
    )

    op.create_table(
        "similarity_checks",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("input_content", sa.Text(), nullable=False),
        sa.Column("normalized_content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("result_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("top_score", sa.Float(), nullable=True),
        sa.Column("results", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_similarity_checks_created_at", "similarity_checks", ["created_at"])


def downgrade() -> None:
    op.drop_table("similarity_checks")
    op.drop_index("ix_content_blocks_embedding_hnsw", table_name="content_blocks")
    op.drop_table("content_blocks")
    op.drop_table("pages")
    op.drop_table("sites")

