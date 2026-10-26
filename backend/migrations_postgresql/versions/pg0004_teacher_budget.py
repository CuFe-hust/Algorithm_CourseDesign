"""Immutable teacher test-suite execution budget; legacy snapshots stay unchanged.

Revision ID: pg0004
Revises: pg0003
"""
from alembic import op
import sqlalchemy as sa

revision = 'pg0004'
down_revision = 'pg0003'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('test_suites', sa.Column('total_budget_ms', sa.Integer(), nullable=True))
    op.create_check_constraint('ck_suite_budget', 'test_suites',
                               'total_budget_ms IS NULL OR total_budget_ms BETWEEN 1000 AND 3600000')


def downgrade():
    op.drop_constraint('ck_suite_budget', 'test_suites', type_='check')
    op.drop_column('test_suites', 'total_budget_ms')
