"""Student authentication increments

Revision ID: pg0002
Revises: pg0001

Adds the first-login password flag, separate idle/absolute session deadlines and
the shared bounded rate limit counters. Existing accounts keep working without an
imposed password change; existing sessions get a conservative 24-hour cap counted
from their original creation time and are never extended by this migration.
"""
from alembic import op
import sqlalchemy as sa

revision = 'pg0002'
down_revision = 'pg0001'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('users', sa.Column('must_change_password', sa.Boolean(), nullable=False,
                                     server_default=sa.false()))
    op.add_column('users', sa.Column('password_updated_at', sa.DateTime(timezone=True), nullable=True))
    op.alter_column('users', 'must_change_password', server_default=None)

    op.add_column('auth_sessions', sa.Column('last_active_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('auth_sessions', sa.Column('absolute_expires_at', sa.DateTime(timezone=True), nullable=True))
    op.execute("UPDATE auth_sessions SET last_active_at = created_at")
    op.execute("UPDATE auth_sessions SET absolute_expires_at = LEAST(created_at + interval '24 hours', expires_at)")
    op.alter_column('auth_sessions', 'last_active_at', nullable=False)
    op.alter_column('auth_sessions', 'absolute_expires_at', nullable=False)
    op.create_index('ix_auth_sessions_absolute_expires_at', 'auth_sessions', ['absolute_expires_at'])

    op.create_table('request_rate_limits',
    sa.Column('bucket', sa.String(length=32), nullable=False),
    sa.Column('subject_hash', sa.String(length=64), nullable=False),
    sa.Column('window_start', sa.DateTime(timezone=True), nullable=False),
    sa.Column('window_seconds', sa.Integer(), nullable=False),
    sa.Column('counter', sa.Integer(), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('id', sa.BigInteger(), sa.Identity(), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint('counter >= 0', name='ck_rate_limit_counter'),
    sa.CheckConstraint('window_seconds > 0', name='ck_rate_limit_window'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_request_rate_limits')),
    sa.UniqueConstraint('bucket', 'subject_hash', 'window_start', 'window_seconds',
                        name=op.f('uq_request_rate_limits_bucket_subject_hash_window_start_window_seconds'))
    )
    op.create_index('ix_request_rate_limits_expires_at', 'request_rate_limits', ['expires_at'])


def downgrade():
    op.drop_index('ix_request_rate_limits_expires_at', table_name='request_rate_limits')
    op.drop_table('request_rate_limits')
    op.drop_index('ix_auth_sessions_absolute_expires_at', table_name='auth_sessions')
    op.drop_column('auth_sessions', 'absolute_expires_at')
    op.drop_column('auth_sessions', 'last_active_at')
    op.drop_column('users', 'password_updated_at')
    op.drop_column('users', 'must_change_password')
