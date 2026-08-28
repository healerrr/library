"""add site email templates

Revision ID: 20260828_0008
Revises: 20260828_0007
Create Date: 2026-08-28
"""

from alembic import op
import sqlalchemy as sa


revision = "20260828_0008"
down_revision = "20260828_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "email_templates",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "site_id",
            sa.BigInteger(),
            sa.ForeignKey("sites.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("content_html", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_email_templates_site_id", "email_templates", ["site_id"])
    op.create_index("ix_email_templates_updated_at", "email_templates", ["updated_at"])


def downgrade() -> None:
    op.drop_index("ix_email_templates_updated_at", table_name="email_templates")
    op.drop_index("ix_email_templates_site_id", table_name="email_templates")
    op.drop_table("email_templates")
