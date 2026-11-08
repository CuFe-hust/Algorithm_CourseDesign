"""Switch complexity reports to execution-trace evidence.

Revision ID: pg0009
Revises: pg0008

The analysis method changed from wall-clock growth fitting plus static
structure rules to exact execution-trace counts and recurrence inference. Three
schema facts follow from that:

1. ``static_analysis`` becomes ``trace_meta`` and ``growth`` becomes
   ``trace_series``: the columns now hold adapter/ladder metadata and per-rung
   counts instead of a fitted timing curve.
2. The published status set changes: ``STATIC_ONLY`` is gone (there is no
   structural fallback any more) and ``NOT_MEASURABLE`` is added for problems
   without a scalable input or languages without a trace adapter. A published
   report is the only state allowed to carry a class.
3. The class vocabulary gains ``O(n!)`` because counted traces can separate
   factorial from exponential growth, and the input-family check gains the new
   generator families used to recover coverage.

Every report written by the old implementation is archived into ``history`` and
reset to ``NOT_MEASURABLE``: keeping the old verdict visible would publish a
conclusion the new implementation cannot reproduce.
"""
from alembic import op

revision = 'pg0009'
down_revision = 'pg0008'
branch_labels = None
depends_on = None

CLASS_VALUES = ', '.join(f"'{value}'" for value in (
    'O(1)', 'O(log n)', 'O(n)', 'O(n log n)', 'O(n^2)', 'O(n^2 log n)',
    'O(n^3)', 'O(2^n)', 'O(n!)', 'UNKNOWN'))

FAMILIES = (
    'SINGLE_INT','TWO_INTS','THREE_INTS','INT_ARRAY',
    'INT_ARRAY_ROWS','INT_ARRAY_QUERIES','INT_ARRAY_WITH_K','SORTED_ARRAY_QUERIES',
    'INT_ARRAY_OPERATIONS','TWO_INT_ARRAYS','INT_ARRAY_ROWS_TWO_HEADER','GRAPH_EDGES',
    'GRAPH_TREE_QUERIES','GRAPH_EDGE_QUERIES','GRAPH_COLORING','TWO_STRINGS',
    'BIG_TWO_STRINGS','STRING_LIST','ONE_STRING','STRING_RANGE_QUERIES',
    'POSTFIX_EXPRESSION','STACK_OPERATIONS','GRID','GRID_WITH_WORD',
    'MATRIX','TRIANGLE_ROWS','KNAPSACK','FIXED',
    'EXISTING_CASES',
)

OLD_CHECKS = ('ck_cr_status', 'ck_cr_status_class', 'ck_cr_time_class',
              'ck_cr_space_class', 'ck_cr_time_source', 'ck_pcp_family')


def upgrade():
    op.alter_column('complexity_reports', 'static_analysis', new_column_name='trace_meta')
    op.alter_column('complexity_reports', 'growth', new_column_name='trace_series')
    for name in OLD_CHECKS:
        table = 'problem_complexity_profiles' if name == 'ck_pcp_family' else 'complexity_reports'
        op.execute(f'ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {name}')

    # Archive every conclusion produced by the wall-clock implementation and turn
    # the row into an explicit "no conclusion" state. The evidence is kept in
    # history so a teacher can see that the verdict changed and why.
    op.execute(
        """
        UPDATE complexity_reports
        SET history = COALESCE(history, '[]'::jsonb) || jsonb_build_array(
                jsonb_build_object(
                    'implementation_name', implementation_name,
                    'implementation_version', implementation_version,
                    'status', status,
                    'time_class', time_class,
                    'space_class', space_class,
                    'summary', summary,
                    'finished_at', CASE WHEN finished_at IS NULL THEN NULL
                                        ELSE to_char(finished_at, 'YYYY-MM-DD"T"HH24:MI:SS.USOF') END)),
            status = 'NOT_MEASURABLE',
            time_class = NULL,
            space_class = NULL,
            time_confidence = NULL,
            space_confidence = NULL,
            time_source = NULL,
            lease_expires_at = NULL,
            finished_at = now(),
            error_message = '旧版复杂度分析（墙钟计时）已下线，请重新请求分析'
        WHERE implementation_name = 'complexity_probe'
        """
    )

    op.execute(
        f"ALTER TABLE complexity_reports ADD CONSTRAINT ck_cr_status CHECK "
        f"(status IN ('PENDING','RUNNING','SUCCEEDED','NOT_MEASURABLE','INELIGIBLE','FAILED'))")
    op.execute(
        f"ALTER TABLE complexity_reports ADD CONSTRAINT ck_cr_time_class CHECK "
        f"(time_class IS NULL OR time_class IN ({CLASS_VALUES}))")
    op.execute(
        f"ALTER TABLE complexity_reports ADD CONSTRAINT ck_cr_space_class CHECK "
        f"(space_class IS NULL OR space_class IN ({CLASS_VALUES}))")
    op.execute(
        "ALTER TABLE complexity_reports ADD CONSTRAINT ck_cr_time_source CHECK "
        "(time_source IS NULL OR time_source IN ('TRACE'))")
    op.execute(
        "ALTER TABLE complexity_reports ADD CONSTRAINT ck_cr_status_class CHECK ("
        "  (status = 'SUCCEEDED' AND time_class IS NOT NULL AND space_class IS NOT NULL)"
        "  OR (status IN ('PENDING','RUNNING','NOT_MEASURABLE','FAILED','INELIGIBLE')"
        "      AND time_class IS NULL AND space_class IS NULL))")
    family_values = ', '.join(f"'{value}'" for value in FAMILIES)
    op.execute(
        "ALTER TABLE problem_complexity_profiles ADD CONSTRAINT ck_pcp_family CHECK "
        f"(family IN ({family_values}))")


def downgrade():
    op.execute('ALTER TABLE problem_complexity_profiles DROP CONSTRAINT IF EXISTS ck_pcp_family')
    for name in ('ck_cr_status_class', 'ck_cr_time_source', 'ck_cr_space_class',
                 'ck_cr_time_class', 'ck_cr_status'):
        op.execute(f'ALTER TABLE complexity_reports DROP CONSTRAINT IF EXISTS {name}')
    # The old vocabulary has no NOT_MEASURABLE; FAILED is the closest state that
    # is allowed to have no class, and the archived history stays in place.
    op.execute("UPDATE complexity_reports SET status = 'FAILED' "
               "WHERE status = 'NOT_MEASURABLE'")
    old_classes = ', '.join(f"'{value}'" for value in (
        'O(1)', 'O(log n)', 'O(n)', 'O(n log n)', 'O(n^2)', 'O(n^2 log n)',
        'O(n^3)', 'O(2^n)', 'UNKNOWN'))
    op.execute(
        "ALTER TABLE complexity_reports ADD CONSTRAINT ck_cr_status CHECK "
        "(status IN ('PENDING','RUNNING','SUCCEEDED','STATIC_ONLY','INELIGIBLE','FAILED'))")
    op.execute(
        f"ALTER TABLE complexity_reports ADD CONSTRAINT ck_cr_time_class CHECK "
        f"(time_class IS NULL OR time_class IN ({old_classes}))")
    op.execute(
        f"ALTER TABLE complexity_reports ADD CONSTRAINT ck_cr_space_class CHECK "
        f"(space_class IS NULL OR space_class IN ({old_classes}))")
    op.execute(
        "ALTER TABLE complexity_reports ADD CONSTRAINT ck_cr_time_source CHECK "
        "(time_source IS NULL OR time_source IN ('DYNAMIC','STATIC'))")
    op.execute(
        "ALTER TABLE complexity_reports ADD CONSTRAINT ck_cr_status_class CHECK ("
        "  (status IN ('SUCCEEDED','STATIC_ONLY') AND time_class IS NOT NULL "
        "   AND space_class IS NOT NULL)"
        "  OR (status IN ('PENDING','RUNNING') AND time_class IS NULL "
        "      AND space_class IS NULL)"
        "  OR status IN ('FAILED','INELIGIBLE'))")
    op.execute(
        "ALTER TABLE problem_complexity_profiles ADD CONSTRAINT ck_pcp_family CHECK "
        "(family IN ('SINGLE_INT','TWO_INTS','INT_ARRAY','INT_ARRAY_ROWS','GRAPH_EDGES',"
        "'TWO_STRINGS','ONE_STRING','GRID','MATRIX','FIXED','EXISTING_CASES'))")
    op.alter_column('complexity_reports', 'trace_meta', new_column_name='static_analysis')
    op.alter_column('complexity_reports', 'trace_series', new_column_name='growth')
