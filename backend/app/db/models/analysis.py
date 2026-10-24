from datetime import datetime
from sqlalchemy import ForeignKey, String, Text, UniqueConstraint, CheckConstraint, Index
from sqlalchemy import BigInteger, DateTime, Integer
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base, Mutable, utcnow


class AnalysisJob(Mutable, Base):
    __tablename__ = 'analysis_jobs'
    submission_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('submissions.id'))
    kind: Mapped[str] = mapped_column(String(32), default='JUDGE')
    status: Mapped[str] = mapped_column(String(16), default='PENDING', index=True)
    parameters: Mapped[dict] = mapped_column(JSONB, default=dict)
    algorithm_name: Mapped[str] = mapped_column(String(64), default='deterministic_mock')
    algorithm_version: Mapped[str] = mapped_column(String(32), default='1')
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    phase: Mapped[str] = mapped_column(String(16), default='QUEUED')
    attempt_no: Mapped[int] = mapped_column(Integer, default=0)
    attempt_token: Mapped[str | None] = mapped_column(String(64))
    owner_id: Mapped[str | None] = mapped_column(String(64))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    recovery_cycle_no: Mapped[int] = mapped_column(Integer, default=0)
    automatic_retries_used: Mapped[int] = mapped_column(Integer, default=0)
    last_manual_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (UniqueConstraint('submission_id', 'kind'), CheckConstraint(
        "status IN ('PENDING','RUNNING','SUCCEEDED','FAILED','CANCELLED')", name='ck_job_status'),
        CheckConstraint('attempt_no >= 0 AND recovery_cycle_no >= 0 AND automatic_retries_used >= 0',
                        name='ck_job_counters_nonnegative'),
        Index('ix_job_dispatch', 'status', 'available_at', 'id'))


class JudgeAttempt(Base):
    """One infrastructure attempt of a judge job.

    Student submissions do not increase when infrastructure retries happen; the
    attempt history keeps the ownership and failure trail per attempt.
    """
    __tablename__ = 'judge_attempts'
    job_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('analysis_jobs.id'), index=True)
    attempt_no: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default='RUNNING')
    execution_mode: Mapped[str | None] = mapped_column(String(16))
    sandbox_ref: Mapped[str | None] = mapped_column(String(128))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_code: Mapped[str | None] = mapped_column(String(32))
    message: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (UniqueConstraint('job_id', 'attempt_no'),
                      CheckConstraint('attempt_no > 0', name='ck_attempt_positive'),
                      CheckConstraint("status IN ('RUNNING','SUCCEEDED','FAILED','ABORTED')", name='ck_attempt_status'))


class JudgeRetryRequest(Base):
    """Idempotency record for a student-initiated rejudge of a failed submission."""
    __tablename__ = 'judge_retry_requests'
    submission_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('submissions.id'), index=True)
    job_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('analysis_jobs.id'))
    requested_by: Mapped[int] = mapped_column(BigInteger, ForeignKey('users.id'))
    client_request_id: Mapped[str] = mapped_column(String(64))
    recovery_cycle_no: Mapped[int] = mapped_column(Integer)
    accepted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (UniqueConstraint('requested_by', 'client_request_id'),
                      CheckConstraint('recovery_cycle_no > 0', name='ck_retry_cycle_positive'))


class JudgeResult(Base):
    __tablename__ = 'judge_results'
    job_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('analysis_jobs.id'), unique=True)
    submission_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('submissions.id'), unique=True)
    verdict: Mapped[str] = mapped_column(String(32))
    is_mock: Mapped[bool]
    algorithm_name: Mapped[str] = mapped_column(String(64))
    algorithm_version: Mapped[str] = mapped_column(String(32))
    cpu_time_ms: Mapped[int | None] = mapped_column(Integer)
    memory_kib: Mapped[int | None] = mapped_column(Integer)
    message: Mapped[str] = mapped_column(Text)
    passed_cases: Mapped[int | None] = mapped_column(Integer)
    executed_cases: Mapped[int | None] = mapped_column(Integer)
    total_cases: Mapped[int | None] = mapped_column(Integer)
    attempt_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey('judge_attempts.id'))
    execution_mode: Mapped[str | None] = mapped_column(String(16), default='MOCK')
    runtime_profile: Mapped[str | None] = mapped_column(String(32))
    measurement_status: Mapped[str | None] = mapped_column(String(24))
    compiler_message: Mapped[str | None] = mapped_column(Text)
    diagnostics_expired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (CheckConstraint('(cpu_time_ms IS NULL OR cpu_time_ms >= 0) AND (memory_kib IS NULL OR memory_kib >= 0)', name='ck_judge_resources_nonnegative'),
        CheckConstraint('NOT is_mock OR (cpu_time_ms IS NULL AND memory_kib IS NULL)', name='ck_mock_resources'),
        CheckConstraint('(passed_cases IS NULL OR passed_cases >= 0) AND (executed_cases IS NULL OR executed_cases >= 0) '
                        'AND (total_cases IS NULL OR total_cases >= 0)', name='ck_judge_counts_nonnegative'),
        CheckConstraint('passed_cases IS NULL OR executed_cases IS NULL OR passed_cases <= executed_cases',
                        name='ck_judge_passed_le_executed'),
        CheckConstraint('executed_cases IS NULL OR total_cases IS NULL OR executed_cases <= total_cases',
                        name='ck_judge_executed_le_total'),
        CheckConstraint("execution_mode IS NULL OR execution_mode IN ('MOCK','LOCAL','LINUX_SANDBOX')",
                        name='ck_judge_execution_mode'),
        CheckConstraint("measurement_status IS NULL OR measurement_status IN "
                        "('MEASURED','UNAVAILABLE_LOCAL','NOT_EXECUTED','NOT_APPLICABLE')",
                        name='ck_judge_measurement_status'))
