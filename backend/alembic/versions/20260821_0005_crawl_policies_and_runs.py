"""add per-site crawl policies and crawl runs

Revision ID: 20260821_0005
Revises: 20260821_0004
"""

from alembic import op
import sqlalchemy as sa


revision = "20260821_0005"
down_revision = "20260821_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sites", sa.Column("include_patterns", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")))
    op.add_column("sites", sa.Column("exclude_patterns", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")))
    op.add_column("sites", sa.Column("allowed_query_params", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")))
    op.add_column("sites", sa.Column("crawler_max_pages", sa.Integer(), nullable=True))
    op.add_column("sites", sa.Column("request_delay_ms", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("sites", sa.Column("min_crawl_coverage", sa.Float(), nullable=False, server_default="0.7"))
    op.create_table(
        "crawl_runs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("site_id", sa.BigInteger(), sa.ForeignKey("sites.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="running"),
        sa.Column("pages_discovered", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("pages_crawled", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("pages_skipped", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("previous_pages", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("retained_pages", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("stale_pages", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("prune_blocked", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("errors", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_crawl_runs_site_id", "crawl_runs", ["site_id"])
    op.create_index("ix_crawl_runs_status", "crawl_runs", ["status"])


def downgrade() -> None:
    op.drop_table("crawl_runs")
    for column_name in (
        "min_crawl_coverage",
        "request_delay_ms",
        "crawler_max_pages",
        "allowed_query_params",
        "exclude_patterns",
        "include_patterns",
    ):
        op.drop_column("sites", column_name)
