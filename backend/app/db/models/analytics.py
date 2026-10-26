"""Batch framework records. Deliberately separate from submission-bound JUDGE."""
from datetime import datetime
from sqlalchemy import BigInteger, String, Integer, ForeignKey, DateTime, CheckConstraint, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base, Mutable


class AnalysisBatch(Mutable, Base):
    __tablename__='analysis_batches'
    course_id:Mapped[int]=mapped_column(BigInteger,ForeignKey('courses.id'),index=True)
    assignment_id:Mapped[int|None]=mapped_column(BigInteger,ForeignKey('assignments.id'))
    created_by:Mapped[int]=mapped_column(BigInteger,ForeignKey('users.id'))
    mode:Mapped[str]=mapped_column(String(16))
    status:Mapped[str]=mapped_column(String(16),default='ACTIVE')
    request_id:Mapped[str]=mapped_column(String(64))
    request_hash:Mapped[str]=mapped_column(String(64))
    seed:Mapped[int]=mapped_column(Integer)
    configuration:Mapped[dict]=mapped_column(JSONB,default=dict)
    events:Mapped[dict]=mapped_column(JSONB,default=dict)
    revision_no:Mapped[int]=mapped_column(Integer,default=0)
    __table_args__=(UniqueConstraint('created_by','request_id'),
        CheckConstraint("mode IN ('DEMO','REAL_INPUT')",name='ck_ab_mode'),
        CheckConstraint("status IN ('ACTIVE','COMPLETE','CANCELLED')",name='ck_ab_status'),
        CheckConstraint('revision_no >= 0',name='ck_ab_revision'))


class AnalysisInputSnapshot(Base):
    __tablename__='analysis_input_snapshots'
    batch_id:Mapped[int]=mapped_column(BigInteger,ForeignKey('analysis_batches.id'),index=True)
    scope:Mapped[str]=mapped_column(String(64))
    input_hash:Mapped[str]=mapped_column(String(64))
    payload:Mapped[dict]=mapped_column(JSONB)
    is_mock:Mapped[bool]
    __table_args__=(UniqueConstraint('batch_id','scope','input_hash'),)


class AnalysisRun(Mutable,Base):
    __tablename__='analysis_runs'
    batch_id:Mapped[int]=mapped_column(BigInteger,ForeignKey('analysis_batches.id'),index=True)
    step_key:Mapped[str]=mapped_column(String(64))
    algorithm_key:Mapped[str|None]=mapped_column(String(64))
    implementation_name:Mapped[str|None]=mapped_column(String(64))
    implementation_version:Mapped[str]=mapped_column(String(32),default='1')
    snapshot_id:Mapped[int|None]=mapped_column(BigInteger,ForeignKey('analysis_input_snapshots.id'))
    dependencies:Mapped[list]=mapped_column(JSONB,default=list)
    dependency_refs:Mapped[list]=mapped_column(JSONB,default=list)
    status:Mapped[str]=mapped_column(String(24),default='WAITING_INPUT',index=True)
    business_status:Mapped[str|None]=mapped_column(String(32))
    reason:Mapped[dict]=mapped_column(JSONB,default=dict)
    attempt_no:Mapped[int]=mapped_column(Integer,default=0)
    attempt_token:Mapped[str|None]=mapped_column(String(64))
    attempt_history:Mapped[list]=mapped_column(JSONB,default=list)
    lease_expires_at:Mapped[datetime|None]=mapped_column(DateTime(timezone=True))
    started_at:Mapped[datetime|None]=mapped_column(DateTime(timezone=True))
    finished_at:Mapped[datetime|None]=mapped_column(DateTime(timezone=True))
    __table_args__=(UniqueConstraint('batch_id','step_key'),
        CheckConstraint("status IN ('WAITING_INPUT','WAITING_HUMAN','READY','RUNNING','SUCCEEDED','FAILED','SKIPPED','CANCELLED')",name='ck_ar_status'),
        CheckConstraint('attempt_no >= 0',name='ck_ar_attempt'))


class AnalysisArtifact(Base):
    __tablename__='analysis_artifacts'
    run_id:Mapped[int]=mapped_column(BigInteger,ForeignKey('analysis_runs.id'),index=True)
    attempt_no:Mapped[int]=mapped_column(Integer)
    output_hash:Mapped[str]=mapped_column(String(64))
    payload:Mapped[dict]=mapped_column(JSONB)
    is_mock:Mapped[bool]
    __table_args__=(UniqueConstraint('run_id','attempt_no'),CheckConstraint('attempt_no >= 0',name='ck_aa_attempt'))
