"""Keep idempotency tokens case-sensitive; do not rewrite applied revision 0001."""
from alembic import op
import sqlalchemy as sa

revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column('submissions', 'client_request_id',
        existing_type=sa.String(64), type_=sa.String(64, collation='utf8mb4_bin'), existing_nullable=False)


def downgrade():
    # May be rejected if differently-cased tokens coexist. Do not discard those submissions.
    op.alter_column('submissions', 'client_request_id',
        existing_type=sa.String(64, collation='utf8mb4_bin'),
        type_=sa.String(64, collation='utf8mb4_0900_ai_ci'), existing_nullable=False)
