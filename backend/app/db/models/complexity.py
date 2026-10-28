"""Complexity profiles (per problem) and per-submission complexity reports.

Both tables are deliberately separate from judging: analysing complexity never
changes a verdict, a score or a submission row.
"""
from datetime import datetime
from sqlalchemy import BigInteger, String, Integer, Text, ForeignKey, DateTime, UniqueConstraint, CheckConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base, Mutable


class ProblemComplexityProfile(Mutable, Base):
    """How to build a size ladder for one frozen problem version.

    The profile is data, not code: a new problem family is added by inserting a
    row, so the generator never needs a per-problem branch.
    """
    __tablename__ = 'problem_complexity_profiles'
    problem_version_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('problem_versions.id'),
                                                    unique=True, index=True)
    family: Mapped[str] = mapped_column(String(32))
    spec: Mapped[dict] = mapped_column(JSONB, default=dict)
    source: Mapped[str] = mapped_column(String(16), default='SEEDED')
    created_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey('users.id'))
    version_no: Mapped[int] = mapped_column(Integer, default=1)
    __table_args__ = (
        CheckConstraint("family IN ('SINGLE_INT','TWO_INTS','INT_ARRAY','INT_ARRAY_ROWS','GRAPH_EDGES',"
                        "'TWO_STRINGS','ONE_STRING','GRID','MATRIX','FIXED','EXISTING_CASES')",
                        name='ck_pcp_family'),
        CheckConstraint("source IN ('SEEDED','TEACHER')", name='ck_pcp_source'),
        CheckConstraint('version_no > 0', name='ck_pcp_version'))


class ComplexityReport(Mutable, Base):
    """One report per submission.

    ``time_class``/``space_class`` are the merged verdict; ``static_analysis``
    and ``growth`` keep the raw evidence so a teacher or a researcher can
    re-derive the conclusion without re-running the program.
    """
    __tablename__ = 'complexity_reports'
    submission_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('submissions.id'), unique=True, index=True)
    assignment_item_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('assignment_items.id'), index=True)
    student_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('users.id'), index=True)
    status: Mapped[str] = mapped_column(String(16), default='PENDING', index=True)
    time_class: Mapped[str | None] = mapped_column(String(16))
    space_class: Mapped[str | None] = mapped_column(String(16))
    time_confidence: Mapped[str | None] = mapped_column(String(8))
    space_confidence: Mapped[str | None] = mapped_column(String(8))
    time_source: Mapped[str | None] = mapped_column(String(8))
    language: Mapped[str | None] = mapped_column(String(32))
    static_analysis: Mapped[dict] = mapped_column(JSONB, default=dict)
    growth: Mapped[dict] = mapped_column(JSONB, default=dict)
    summary: Mapped[dict] = mapped_column(JSONB, default=dict)
    limitations: Mapped[list] = mapped_column(JSONB, default=list)
    implementation_name: Mapped[str] = mapped_column(String(64))
    implementation_version: Mapped[str] = mapped_column(String(32), default='1')
    requested_by: Mapped[int] = mapped_column(BigInteger, ForeignKey('users.id'))
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    attempt_no: Mapped[int] = mapped_column(Integer, default=0)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)
    # Every superseded conclusion, appended when an implementation change resets
    # the row. A teacher who read the previous verdict can see it changed.
    history: Mapped[list] = mapped_column(JSONB, default=list)
    __table_args__ = (
        CheckConstraint("status IN ('PENDING','RUNNING','SUCCEEDED','STATIC_ONLY','INELIGIBLE','FAILED')",
                        name='ck_cr_status'),
        CheckConstraint('attempt_no >= 0', name='ck_cr_attempt'),
        CheckConstraint("time_confidence IS NULL OR time_confidence IN ('LOW','MEDIUM','HIGH')",
                        name='ck_cr_time_conf'),
        CheckConstraint("space_confidence IS NULL OR space_confidence IN ('LOW','MEDIUM','HIGH')",
                        name='ck_cr_space_conf'),
        CheckConstraint("time_source IS NULL OR time_source IN ('DYNAMIC','STATIC')",
                        name='ck_cr_time_source'),
        CheckConstraint("time_class IS NULL OR time_class IN "
                        "('O(1)','O(log n)','O(n)','O(n log n)','O(n^2)','O(n^2 log n)',"
                        "'O(n^3)','O(2^n)','UNKNOWN')", name='ck_cr_time_class'),
        CheckConstraint("space_class IS NULL OR space_class IN "
                        "('O(1)','O(log n)','O(n)','O(n log n)','O(n^2)','O(n^2 log n)',"
                        "'O(n^3)','O(2^n)','UNKNOWN')", name='ck_cr_space_class'),
        # A published report must carry its verdict; a queued one must not.
        CheckConstraint("(status IN ('SUCCEEDED','STATIC_ONLY') "
                        "AND time_class IS NOT NULL AND space_class IS NOT NULL) "
                        "OR (status IN ('PENDING','RUNNING') "
                        "AND time_class IS NULL AND space_class IS NULL) "
                        "OR status IN ('FAILED','INELIGIBLE')", name='ck_cr_status_class'))
