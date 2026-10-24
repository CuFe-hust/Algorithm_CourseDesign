"""Judge lifecycle, attempts and summary increments

Revision ID: pg0003
Revises: pg0002

Existing jobs and results are conservatively interpreted as MOCK: the migration
never backfills real pass counts or resources, and never turns a mock verdict into
a real one. LOCAL results are allowed to keep NULL resources.
"""
from alembic import op
import sqlalchemy as sa

revision = 'pg0003'
down_revision = 'pg0002'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('analysis_jobs', sa.Column('available_at', sa.DateTime(timezone=True), nullable=True,
                                             server_default=sa.text('now()')))
    op.add_column('analysis_jobs', sa.Column('phase', sa.String(length=16), nullable=False,
                                             server_default='QUEUED'))
    op.add_column('analysis_jobs', sa.Column('attempt_no', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('analysis_jobs', sa.Column('attempt_token', sa.String(length=64), nullable=True))
    op.add_column('analysis_jobs', sa.Column('owner_id', sa.String(length=64), nullable=True))
    op.add_column('analysis_jobs', sa.Column('heartbeat_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('analysis_jobs', sa.Column('lease_expires_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('analysis_jobs', sa.Column('recovery_cycle_no', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('analysis_jobs', sa.Column('automatic_retries_used', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('analysis_jobs', sa.Column('last_manual_retry_at', sa.DateTime(timezone=True), nullable=True))
    op.execute('UPDATE analysis_jobs SET available_at = created_at WHERE available_at IS NULL')
    op.alter_column('analysis_jobs', 'available_at', nullable=False)
    for column in ('phase', 'attempt_no', 'recovery_cycle_no', 'automatic_retries_used'):
        op.alter_column('analysis_jobs', column, server_default=None)
    op.create_check_constraint('ck_job_counters_nonnegative', 'analysis_jobs',
                              'attempt_no >= 0 AND recovery_cycle_no >= 0 AND automatic_retries_used >= 0')
    op.create_index('ix_analysis_jobs_lease_expires_at', 'analysis_jobs', ['lease_expires_at'])
    op.create_index('ix_job_dispatch', 'analysis_jobs', ['status', 'available_at', 'id'])

    op.create_table('judge_attempts',
    sa.Column('job_id', sa.BigInteger(), nullable=False),
    sa.Column('attempt_no', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('execution_mode', sa.String(length=16), nullable=True),
    sa.Column('sandbox_ref', sa.String(length=128), nullable=True),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('failure_code', sa.String(length=32), nullable=True),
    sa.Column('message', sa.Text(), nullable=True),
    sa.Column('id', sa.BigInteger(), sa.Identity(), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint('attempt_no > 0', name='ck_attempt_positive'),
    sa.CheckConstraint("status IN ('RUNNING','SUCCEEDED','FAILED','ABORTED')", name='ck_attempt_status'),
    sa.ForeignKeyConstraint(['job_id'], ['analysis_jobs.id'], name=op.f('fk_judge_attempts_job_id_analysis_jobs')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_judge_attempts')),
    sa.UniqueConstraint('job_id', 'attempt_no', name=op.f('uq_judge_attempts_job_id_attempt_no'))
    )
    op.create_index('ix_judge_attempts_job_id', 'judge_attempts', ['job_id'])

    op.create_table('judge_retry_requests',
    sa.Column('submission_id', sa.BigInteger(), nullable=False),
    sa.Column('job_id', sa.BigInteger(), nullable=False),
    sa.Column('requested_by', sa.BigInteger(), nullable=False),
    sa.Column('client_request_id', sa.String(length=64), nullable=False),
    sa.Column('recovery_cycle_no', sa.Integer(), nullable=False),
    sa.Column('accepted_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('id', sa.BigInteger(), sa.Identity(), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint('recovery_cycle_no > 0', name='ck_retry_cycle_positive'),
    sa.ForeignKeyConstraint(['job_id'], ['analysis_jobs.id'], name=op.f('fk_judge_retry_requests_job_id_analysis_jobs')),
    sa.ForeignKeyConstraint(['requested_by'], ['users.id'], name=op.f('fk_judge_retry_requests_requested_by_users')),
    sa.ForeignKeyConstraint(['submission_id'], ['submissions.id'], name=op.f('fk_judge_retry_requests_submission_id_submissions')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_judge_retry_requests')),
    sa.UniqueConstraint('requested_by', 'client_request_id', name=op.f('uq_judge_retry_requests_requested_by_client_request_id'))
    )
    op.create_index('ix_judge_retry_requests_submission_id', 'judge_retry_requests', ['submission_id'])

    op.add_column('judge_results', sa.Column('passed_cases', sa.Integer(), nullable=True))
    op.add_column('judge_results', sa.Column('executed_cases', sa.Integer(), nullable=True))
    op.add_column('judge_results', sa.Column('total_cases', sa.Integer(), nullable=True))
    op.add_column('judge_results', sa.Column('attempt_id', sa.BigInteger(), nullable=True))
    op.add_column('judge_results', sa.Column('execution_mode', sa.String(length=16), nullable=True,
                                             server_default='MOCK'))
    op.add_column('judge_results', sa.Column('runtime_profile', sa.String(length=32), nullable=True))
    op.add_column('judge_results', sa.Column('measurement_status', sa.String(length=24), nullable=True))
    op.add_column('judge_results', sa.Column('compiler_message', sa.Text(), nullable=True))
    op.add_column('judge_results', sa.Column('diagnostics_expired_at', sa.DateTime(timezone=True), nullable=True))
    op.execute("UPDATE judge_results SET execution_mode = 'MOCK' WHERE is_mock")
    op.execute("UPDATE judge_results SET measurement_status = 'NOT_APPLICABLE' WHERE is_mock")
    op.alter_column('judge_results', 'execution_mode', server_default=None)
    op.create_foreign_key(op.f('fk_judge_results_attempt_id_judge_attempts'), 'judge_results', 'judge_attempts',
                          ['attempt_id'], ['id'])
    op.create_check_constraint('ck_judge_counts_nonnegative', 'judge_results',
                              '(passed_cases IS NULL OR passed_cases >= 0) AND (executed_cases IS NULL OR executed_cases >= 0) '
                              'AND (total_cases IS NULL OR total_cases >= 0)')
    op.create_check_constraint('ck_judge_passed_le_executed', 'judge_results',
                              'passed_cases IS NULL OR executed_cases IS NULL OR passed_cases <= executed_cases')
    op.create_check_constraint('ck_judge_executed_le_total', 'judge_results',
                              'executed_cases IS NULL OR total_cases IS NULL OR executed_cases <= total_cases')
    op.create_check_constraint('ck_judge_execution_mode', 'judge_results',
                              "execution_mode IS NULL OR execution_mode IN ('MOCK','LOCAL','LINUX_SANDBOX')")
    op.create_check_constraint('ck_judge_measurement_status', 'judge_results',
                              "measurement_status IS NULL OR measurement_status IN "
                              "('MEASURED','UNAVAILABLE_LOCAL','NOT_EXECUTED','NOT_APPLICABLE')")


def downgrade():
    for constraint in ('ck_judge_measurement_status', 'ck_judge_execution_mode', 'ck_judge_executed_le_total',
                       'ck_judge_passed_le_executed', 'ck_judge_counts_nonnegative'):
        op.drop_constraint(constraint, 'judge_results', type_='check')
    op.drop_constraint(op.f('fk_judge_results_attempt_id_judge_attempts'), 'judge_results', type_='foreignkey')
    for column in ('diagnostics_expired_at', 'compiler_message', 'measurement_status', 'runtime_profile',
                   'execution_mode', 'attempt_id', 'total_cases', 'executed_cases', 'passed_cases'):
        op.drop_column('judge_results', column)
    op.drop_index('ix_judge_retry_requests_submission_id', table_name='judge_retry_requests')
    op.drop_table('judge_retry_requests')
    op.drop_index('ix_judge_attempts_job_id', table_name='judge_attempts')
    op.drop_table('judge_attempts')
    op.drop_index('ix_job_dispatch', table_name='analysis_jobs')
    op.drop_index('ix_analysis_jobs_lease_expires_at', table_name='analysis_jobs')
    op.drop_constraint('ck_job_counters_nonnegative', 'analysis_jobs', type_='check')
    for column in ('last_manual_retry_at', 'automatic_retries_used', 'recovery_cycle_no', 'lease_expires_at',
                   'heartbeat_at', 'owner_id', 'attempt_token', 'attempt_no', 'phase', 'available_at'):
        op.drop_column('analysis_jobs', column)
