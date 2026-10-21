from datetime import datetime
from sqlalchemy import ForeignKey, String, UniqueConstraint, CheckConstraint, Index
from sqlalchemy import BigInteger, Integer, Text, DateTime
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base


class Submission(Base):
    __tablename__ = 'submissions'
    assignment_item_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('assignment_items.id'))
    student_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('users.id'))
    version_no: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    language: Mapped[str | None] = mapped_column(String(32))
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), default='SUBMITTED')
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    client_request_id: Mapped[str] = mapped_column(String(64))
    __table_args__ = (UniqueConstraint('assignment_item_id', 'student_id', 'version_no'),
        UniqueConstraint('student_id', 'client_request_id'),
        Index('ix_submission_history', 'assignment_item_id', 'student_id', 'submitted_at'),
        CheckConstraint('version_no > 0', name='ck_submission_version'),
        CheckConstraint("(status='SUBMITTED' AND withdrawn_at IS NULL) OR (status='WITHDRAWN' AND withdrawn_at IS NOT NULL)", name='ck_submission_status'))
