"""add site_scheme column

Revision ID: 20260824_0006
Revises: 20260821_0005
Create Date: 2026-08-24

"""
from alembic import op
import sqlalchemy as sa


revision = '20260824_0006'
down_revision = '20260821_0005'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('sites', sa.Column('site_scheme', sa.String(8), nullable=False, server_default='https'))


def downgrade() -> None:
    op.drop_column('sites', 'site_scheme')
