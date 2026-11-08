"""Complexity report integrity constraints and conclusion history.

Two gaps found in scheme review:

1. ``time_class``/``space_class`` accepted any string, and nothing tied them to
   the report status, so a bug could publish a class on a PENDING row (or store
   a class the fitter can never produce).
2. When the implementation version changed, ``request_report`` reset the row to
   PENDING and overwrote the previous conclusion; a teacher who had read the old
   verdict had no way to notice it changed. The row now keeps a ``history`` array
   with every superseded conclusion.

Revision ID: pg0008
Revises: pg0007
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = 'pg0008'
down_revision = 'pg0007'


CLASS_VALUES = ', '.join(f"'{value}'" for value in (
    'O(1)', 'O(log n)', 'O(n)', 'O(n log n)', 'O(n^2)', 'O(n^2 log n)',
    'O(n^3)', 'O(2^n)', 'UNKNOWN'))


def upgrade():
    op.execute(
        'ALTER TABLE complexity_reports ADD CONSTRAINT ck_cr_time_class '
        f'CHECK (time_class IS NULL OR time_class IN ({CLASS_VALUES}))')
    op.execute(
        'ALTER TABLE complexity_reports ADD CONSTRAINT ck_cr_space_class '
        f'CHECK (space_class IS NULL OR space_class IN ({CLASS_VALUES}))')
    op.execute(
        'ALTER TABLE complexity_reports ADD CONSTRAINT ck_cr_status_class CHECK ('
        "  (status IN ('SUCCEEDED','STATIC_ONLY') AND time_class IS NOT NULL AND space_class IS NOT NULL)"
        "  OR (status IN ('PENDING','RUNNING') AND time_class IS NULL AND space_class IS NULL)"
        "  OR status IN ('FAILED','INELIGIBLE'))")
    op.add_column('complexity_reports',
                  sa.Column('history', JSONB(), nullable=False, server_default='[]'))


def downgrade():
    op.drop_column('complexity_reports', 'history')
    op.execute('ALTER TABLE complexity_reports DROP CONSTRAINT IF EXISTS ck_cr_status_class')
    op.execute('ALTER TABLE complexity_reports DROP CONSTRAINT IF EXISTS ck_cr_space_class')
    op.execute('ALTER TABLE complexity_reports DROP CONSTRAINT IF EXISTS ck_cr_time_class')
