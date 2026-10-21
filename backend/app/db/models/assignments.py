from datetime import datetime
from decimal import Decimal
from sqlalchemy import ForeignKey, String, Text, UniqueConstraint, CheckConstraint, Numeric
from sqlalchemy import BigInteger, DateTime, Integer, SmallInteger
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base, Mutable


class Assignment(Mutable, Base):
    __tablename__ = 'assignments'
    course_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('courses.id'), index=True)
    title: Mapped[str] = mapped_column(String(200))
    description_md: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int] = mapped_column(BigInteger, ForeignKey('users.id'))
    submission_deadline: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    review_deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    submission_status: Mapped[str] = mapped_column(String(16), default='DRAFT')
    published_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey('users.id'))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        CheckConstraint("submission_status IN ('DRAFT','OPEN','CLOSED')", name='ck_assignment_status'),
        CheckConstraint('review_deadline IS NULL OR review_deadline > submission_deadline', name='ck_assignment_deadlines'),
        CheckConstraint("submission_status='DRAFT' OR (published_by IS NOT NULL AND published_at IS NOT NULL AND published_at < submission_deadline)", name='ck_assignment_published'))


class AssignmentItem(Mutable, Base):
    __tablename__ = 'assignment_items'
    assignment_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('assignments.id'))
    problem_version_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('problem_versions.id'))
    sort_order: Mapped[int] = mapped_column(Integer)
    max_score: Mapped[Decimal] = mapped_column(Numeric(8, 2))
    score_weight: Mapped[Decimal] = mapped_column(Numeric(8, 6))
    required_reviewers: Mapped[int] = mapped_column(SmallInteger, default=0)
    test_suite_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey('test_suites.id'))
    rubric_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey('rubrics.id'))
    __table_args__ = (UniqueConstraint('assignment_id', 'sort_order'), UniqueConstraint('assignment_id', 'problem_version_id'),
        CheckConstraint('sort_order >= 0 AND required_reviewers >= 0', name='ck_item_nonnegative'),
        CheckConstraint('max_score > 0 AND score_weight > 0 AND score_weight <= 1', name='ck_item_scores'),
        CheckConstraint('(test_suite_id IS NOT NULL AND rubric_id IS NULL AND required_reviewers=0) OR (test_suite_id IS NULL AND rubric_id IS NOT NULL AND required_reviewers>0)', name='ck_item_config'))


class AssignmentParticipant(Base):
    __tablename__ = 'assignment_participants'
    assignment_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('assignments.id'))
    student_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('users.id'), index=True)
    class_id_at_publish: Mapped[int] = mapped_column(BigInteger, ForeignKey('classes.id'))
    class_name_at_publish: Mapped[str] = mapped_column(String(100))
    __table_args__ = (UniqueConstraint('assignment_id', 'student_id'),)
