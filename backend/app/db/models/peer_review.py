"""Append-only peer-review facts; algorithms remain in the shared batch framework."""
from datetime import datetime
from decimal import Decimal
from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base, Mutable


class ReviewRound(Mutable, Base):
    __tablename__ = 'review_rounds'
    course_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('courses.id'), index=True)
    assignment_item_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('assignment_items.id'), index=True)
    root_round_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey('review_rounds.id'), index=True)
    round_no: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default='PREVIEW')
    revision_no: Mapped[int] = mapped_column(Integer, default=0)
    created_by: Mapped[int] = mapped_column(BigInteger, ForeignKey('users.id'))
    reason: Mapped[str] = mapped_column(Text)
    policy: Mapped[dict] = mapped_column(JSONB)
    source_hash: Mapped[str] = mapped_column(String(64))
    allocation_batch_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey('analysis_batches.id'), unique=True)
    review_deadline: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey('users.id'))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey('users.id'))
    close_reason: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (
        UniqueConstraint('assignment_item_id', 'round_no'),
        CheckConstraint("status IN ('PREVIEW','OPEN','CLOSED','CANCELLED')", name='ck_rr_status'),
        CheckConstraint('round_no > 0 AND revision_no >= 0', name='ck_rr_numbers'),
        CheckConstraint("status NOT IN ('OPEN','CLOSED') OR (published_at IS NOT NULL AND published_by IS NOT NULL)", name='ck_rr_published'),
        CheckConstraint("status != 'CLOSED' OR (closed_at IS NOT NULL AND closed_by IS NOT NULL)", name='ck_rr_closed'),
        Index('uq_rr_primary', 'assignment_item_id', unique=True,
              postgresql_where=text("root_round_id IS NULL AND status != 'CANCELLED'")),
        Index('uq_rr_supplement_active', 'root_round_id', unique=True,
              postgresql_where=text("root_round_id IS NOT NULL AND status IN ('PREVIEW','OPEN')")),
    )


class ReviewTask(Mutable, Base):
    __tablename__ = 'review_tasks'
    round_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('review_rounds.id'), index=True)
    submission_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('submissions.id'))
    answer_key: Mapped[str] = mapped_column(String(64))
    reviewer_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('users.id'), index=True)
    status: Mapped[str] = mapped_column(String(16), default='ASSIGNED')
    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        UniqueConstraint('round_id', 'answer_key', 'reviewer_id'),
        CheckConstraint("status IN ('ASSIGNED','SUBMITTED')", name='ck_rt_status'),
        CheckConstraint("status != 'SUBMITTED' OR (opened_at IS NOT NULL AND submitted_at IS NOT NULL)", name='ck_rt_submitted'),
    )


class ReviewEvaluation(Base):
    __tablename__ = 'review_evaluations'
    task_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('review_tasks.id'), unique=True)
    reviewer_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('users.id'))
    client_request_id: Mapped[str] = mapped_column(String(64))
    request_hash: Mapped[str] = mapped_column(String(64))
    dimension_scores: Mapped[list] = mapped_column(JSONB)
    total_score: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    comment: Mapped[str] = mapped_column(Text)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    elapsed_seconds: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    __table_args__ = (
        UniqueConstraint('reviewer_id', 'client_request_id'),
        CheckConstraint('total_score >= 0 AND elapsed_seconds >= 0', name='ck_re_numbers'),
        CheckConstraint('submitted_at >= opened_at', name='ck_re_times'),
    )


class ReviewAnalysis(Mutable, Base):
    __tablename__ = 'review_analyses'
    root_round_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('review_rounds.id'), index=True)
    version_no: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(16))
    batch_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('analysis_batches.id'), unique=True)
    source_hash: Mapped[str] = mapped_column(String(64))
    created_by: Mapped[int] = mapped_column(BigInteger, ForeignKey('users.id'))
    resolved_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey('users.id'))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolution_reason: Mapped[str | None] = mapped_column(Text)
    acknowledged_statuses: Mapped[dict] = mapped_column(JSONB, default=dict)
    __table_args__ = (
        UniqueConstraint('root_round_id', 'version_no'),
        CheckConstraint('version_no > 0', name='ck_ra_version'),
        CheckConstraint("kind IN ('INITIAL','RECOMPUTE')", name='ck_ra_kind'),
    )


class ReviewDecision(Base):
    __tablename__ = 'review_decisions'
    root_round_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('review_rounds.id'), index=True)
    analysis_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('review_analyses.id'))
    evaluation_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey('review_evaluations.id'))
    answer_key: Mapped[str | None] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(16))
    weight: Mapped[Decimal | None] = mapped_column(Numeric(8, 6))
    override_score: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    reason: Mapped[str] = mapped_column(Text)
    created_by: Mapped[int] = mapped_column(BigInteger, ForeignKey('users.id'))
    __table_args__ = (
        CheckConstraint('(evaluation_id IS NULL) != (answer_key IS NULL)', name='ck_rd_target'),
        CheckConstraint("action IN ('KEEP','DOWNWEIGHT','INVALIDATE','OVERRIDE')", name='ck_rd_action'),
        CheckConstraint("action != 'DOWNWEIGHT' OR (evaluation_id IS NOT NULL AND weight IS NOT NULL AND weight > 0 AND weight <= 1)", name='ck_rd_weight'),
        CheckConstraint("action != 'OVERRIDE' OR (answer_key IS NOT NULL AND override_score IS NOT NULL AND override_score >= 0)", name='ck_rd_override'),
    )


class ReviewCommand(Base):
    __tablename__ = 'review_commands'
    actor_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('users.id'))
    request_id: Mapped[str] = mapped_column(String(64))
    request_hash: Mapped[str] = mapped_column(String(64))
    operation: Mapped[str] = mapped_column(String(32))
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    round_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('review_rounds.id'))
    analysis_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey('review_analyses.id'))
    __table_args__ = (UniqueConstraint('actor_id', 'request_id'),)
