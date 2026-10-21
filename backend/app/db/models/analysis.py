from datetime import datetime
from sqlalchemy import ForeignKey, String, Text, UniqueConstraint, CheckConstraint, JSON
from sqlalchemy.dialects.mysql import BIGINT, DATETIME, INTEGER
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base, Mutable


class AnalysisJob(Mutable, Base):
    __tablename__ = 'analysis_jobs'
    submission_id: Mapped[int] = mapped_column(BIGINT(unsigned=True), ForeignKey('submissions.id'))
    kind: Mapped[str] = mapped_column(String(32), default='JUDGE')
    status: Mapped[str] = mapped_column(String(16), default='PENDING', index=True)
    parameters: Mapped[dict] = mapped_column(JSON, default=dict)
    algorithm_name: Mapped[str] = mapped_column(String(64), default='deterministic_mock')
    algorithm_version: Mapped[str] = mapped_column(String(32), default='1')
    started_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6))
    finished_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6))
    error_message: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (UniqueConstraint('submission_id', 'kind'), CheckConstraint(
        "status IN ('PENDING','RUNNING','SUCCEEDED','FAILED','CANCELLED')", name='ck_job_status'))


class JudgeResult(Base):
    __tablename__ = 'judge_results'
    job_id: Mapped[int] = mapped_column(BIGINT(unsigned=True), ForeignKey('analysis_jobs.id'), unique=True)
    submission_id: Mapped[int] = mapped_column(BIGINT(unsigned=True), ForeignKey('submissions.id'), unique=True)
    verdict: Mapped[str] = mapped_column(String(32))
    is_mock: Mapped[bool]
    algorithm_name: Mapped[str] = mapped_column(String(64))
    algorithm_version: Mapped[str] = mapped_column(String(32))
    cpu_time_ms: Mapped[int | None] = mapped_column(INTEGER(unsigned=True))
    memory_kib: Mapped[int | None] = mapped_column(INTEGER(unsigned=True))
    message: Mapped[str] = mapped_column(Text)
    __table_args__ = (CheckConstraint('is_mock=0 OR (cpu_time_ms IS NULL AND memory_kib IS NULL)', name='ck_mock_resources'),)
