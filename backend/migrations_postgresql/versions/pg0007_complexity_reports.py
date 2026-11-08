"""Add per-problem scale profiles and per-submission complexity reports.

Revision ID: pg0007
Revises: pg0006

Two new tables only. Judging rows, verdicts and scores are untouched: a
complexity report never changes what a submission was judged as.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
revision = 'pg0007'
down_revision = 'pg0006'
branch_labels = None
depends_on = None

def upgrade():
    op.create_table('problem_complexity_profiles',
    sa.Column('problem_version_id', sa.BigInteger(), nullable=False),
    sa.Column('family', sa.String(length=32), nullable=False),
    sa.Column('spec', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('source', sa.String(length=16), nullable=False),
    sa.Column('created_by', sa.BigInteger(), nullable=True),
    sa.Column('version_no', sa.Integer(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("family IN ('SINGLE_INT','TWO_INTS','INT_ARRAY','INT_ARRAY_ROWS','GRAPH_EDGES','TWO_STRINGS','ONE_STRING','GRID','MATRIX','FIXED','EXISTING_CASES')", name='ck_pcp_family'),
    sa.CheckConstraint("source IN ('SEEDED','TEACHER')", name='ck_pcp_source'),
    sa.CheckConstraint('version_no > 0', name='ck_pcp_version'),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], name=op.f('fk_problem_complexity_profiles_created_by_users')),
    sa.ForeignKeyConstraint(['problem_version_id'], ['problem_versions.id'], name=op.f('fk_problem_complexity_profiles_problem_version_id_problem_versions')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_problem_complexity_profiles'))
    )
    op.create_index(op.f('ix_problem_complexity_profiles_problem_version_id'), 'problem_complexity_profiles', ['problem_version_id'], unique=True)
    op.create_table('complexity_reports',
    sa.Column('submission_id', sa.BigInteger(), nullable=False),
    sa.Column('assignment_item_id', sa.BigInteger(), nullable=False),
    sa.Column('student_id', sa.BigInteger(), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('time_class', sa.String(length=16), nullable=True),
    sa.Column('space_class', sa.String(length=16), nullable=True),
    sa.Column('time_confidence', sa.String(length=8), nullable=True),
    sa.Column('space_confidence', sa.String(length=8), nullable=True),
    sa.Column('time_source', sa.String(length=8), nullable=True),
    sa.Column('language', sa.String(length=32), nullable=True),
    sa.Column('static_analysis', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('growth', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('summary', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('limitations', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('implementation_name', sa.String(length=64), nullable=False),
    sa.Column('implementation_version', sa.String(length=32), nullable=False),
    sa.Column('requested_by', sa.BigInteger(), nullable=False),
    sa.Column('requested_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('attempt_no', sa.Integer(), nullable=False),
    sa.Column('lease_expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('error_message', sa.Text(), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("space_confidence IS NULL OR space_confidence IN ('LOW','MEDIUM','HIGH')", name='ck_cr_space_conf'),
    sa.CheckConstraint("status IN ('PENDING','RUNNING','SUCCEEDED','STATIC_ONLY','INELIGIBLE','FAILED')", name='ck_cr_status'),
    sa.CheckConstraint("time_confidence IS NULL OR time_confidence IN ('LOW','MEDIUM','HIGH')", name='ck_cr_time_conf'),
    sa.CheckConstraint("time_source IS NULL OR time_source IN ('DYNAMIC','STATIC')", name='ck_cr_time_source'),
    sa.CheckConstraint('attempt_no >= 0', name='ck_cr_attempt'),
    sa.ForeignKeyConstraint(['assignment_item_id'], ['assignment_items.id'], name=op.f('fk_complexity_reports_assignment_item_id_assignment_items')),
    sa.ForeignKeyConstraint(['requested_by'], ['users.id'], name=op.f('fk_complexity_reports_requested_by_users')),
    sa.ForeignKeyConstraint(['student_id'], ['users.id'], name=op.f('fk_complexity_reports_student_id_users')),
    sa.ForeignKeyConstraint(['submission_id'], ['submissions.id'], name=op.f('fk_complexity_reports_submission_id_submissions')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_complexity_reports'))
    )
    op.create_index(op.f('ix_complexity_reports_assignment_item_id'), 'complexity_reports', ['assignment_item_id'], unique=False)
    op.create_index(op.f('ix_complexity_reports_lease_expires_at'), 'complexity_reports', ['lease_expires_at'], unique=False)
    op.create_index(op.f('ix_complexity_reports_status'), 'complexity_reports', ['status'], unique=False)
    op.create_index(op.f('ix_complexity_reports_student_id'), 'complexity_reports', ['student_id'], unique=False)
    op.create_index(op.f('ix_complexity_reports_submission_id'), 'complexity_reports', ['submission_id'], unique=True)

def downgrade():
    op.drop_index(op.f('ix_complexity_reports_submission_id'), table_name='complexity_reports')
    op.drop_index(op.f('ix_complexity_reports_student_id'), table_name='complexity_reports')
    op.drop_index(op.f('ix_complexity_reports_status'), table_name='complexity_reports')
    op.drop_index(op.f('ix_complexity_reports_lease_expires_at'), table_name='complexity_reports')
    op.drop_index(op.f('ix_complexity_reports_assignment_item_id'), table_name='complexity_reports')
    op.drop_table('complexity_reports')
    op.drop_index(op.f('ix_problem_complexity_profiles_problem_version_id'), table_name='problem_complexity_profiles')
    op.drop_table('problem_complexity_profiles')
