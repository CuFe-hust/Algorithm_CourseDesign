"""Remove assignment aggregation weights; fence old analysis batches."""
from alembic import op
import sqlalchemy as sa

revision='pg0006'
down_revision='pg0005'
branch_labels=None
depends_on=None


def upgrade():
    op.drop_constraint('ck_item_scores','assignment_items',type_='check')
    op.drop_column('assignment_items','score_weight')
    op.create_check_constraint('ck_item_scores','assignment_items','max_score > 0')
    # Immutable historical artifacts remain historical. Old workers are fenced;
    # no old batch may execute under the changed graph/contract.
    op.execute("UPDATE analysis_batches SET status='CANCELLED' WHERE configuration->>'schema_version' IS DISTINCT FROM 'analysis-v2'")
    op.execute("UPDATE analysis_runs SET status='CANCELLED',attempt_token=NULL,lease_expires_at=NULL,reason='{\"reason\":\"ANALYSIS_SCHEMA_UPDATED\"}'::jsonb WHERE status NOT IN ('SUCCEEDED','SKIPPED','CANCELLED') AND batch_id IN (SELECT id FROM analysis_batches WHERE status='CANCELLED')")


def downgrade():
    op.drop_constraint('ck_item_scores','assignment_items',type_='check')
    op.add_column('assignment_items',sa.Column('score_weight',sa.Numeric(8,6),nullable=False,server_default='1'))
    op.alter_column('assignment_items','score_weight',server_default=None)
    op.create_check_constraint('ck_item_scores','assignment_items','max_score > 0 AND score_weight > 0 AND score_weight <= 1')
    # Cancelled old batches remain fenced; downgrade cannot restore retired weights.
