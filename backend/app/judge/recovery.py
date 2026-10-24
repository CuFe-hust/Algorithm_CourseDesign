"""Lease expiry recovery.

Order matters: take the per-job lifecycle lock, revoke the old token, terminate
the recorded execution, confirm cleanup, and only then requeue or fail the job.
A late starter that acquires L(job) afterwards finds a revoked token and is
refused by the supervisor, so no second copy of the program can run.
"""
from __future__ import annotations

import uuid
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.db.base import utcnow
from app.db.models import AnalysisJob, JudgeAttempt
from app.judge import config, locks
from app.judge.supervisor import SUPERVISOR, read_marker, terminate_marker


def recover_job(engine, job_id: int, now=None) -> str:
    now = now or utcnow()
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        lock = locks.job_lock(job_id, blocking=False)
        lock.__enter__()
    except BlockingIOError:
        return 'busy'
    try:
        with factory() as db:
            job = db.scalar(select(AnalysisJob).where(AnalysisJob.id == job_id).with_for_update())
            if job is None or job.status != 'RUNNING':
                db.rollback()
                return 'skipped'
            lease = job.lease_expires_at
            if lease is not None and lease > now:
                db.rollback()
                return 'skipped'
            recovery_token = f'recovery-{uuid.uuid4().hex}'
            job.attempt_token = recovery_token
            job.phase = 'RECOVERING'
            job.heartbeat_at = None
            attempt_no = job.attempt_no
            db.commit()
        SUPERVISOR.terminate(job_id)
        marker = read_marker(job_id)
        if marker is not None:
            terminate_marker(marker)
        with factory() as db:
            job = db.scalar(select(AnalysisJob).where(AnalysisJob.id == job_id).with_for_update())
            if job is None or job.status != 'RUNNING' or job.attempt_token != recovery_token:
                db.rollback()
                return 'lost'
            attempt = db.scalar(select(JudgeAttempt).where(JudgeAttempt.job_id == job_id,
                                                          JudgeAttempt.attempt_no == attempt_no))
            if attempt is not None and attempt.status == 'RUNNING':
                attempt.status = 'ABORTED'
                attempt.finished_at = now
                attempt.failure_code = 'LEASE_EXPIRED'
                attempt.message = '执行所有权丢失，旧执行已清理'
            job.attempt_token = None
            job.owner_id = None
            job.heartbeat_at = None
            job.lease_expires_at = None
            budget_left = job.automatic_retries_used < config.AUTO_RETRIES_PER_CYCLE
            if budget_left:
                backoff = config.AUTO_RETRY_BACKOFF[min(job.automatic_retries_used,
                                                        len(config.AUTO_RETRY_BACKOFF) - 1)]
                job.automatic_retries_used += 1
                job.status = 'PENDING'
                job.phase = 'RETRY_WAIT'
                job.available_at = now + timedelta(seconds=backoff)
                job.error_message = 'LEASE_EXPIRED: 执行器租约过期，已清理旧执行并安排重试'
                outcome = 'requeued'
            else:
                job.status = 'FAILED'
                job.phase = 'FINISHED'
                job.finished_at = now
                job.error_message = 'LEASE_EXPIRED: 执行器租约过期，自动重试预算已用尽'
                outcome = 'failed'
            db.commit()
            return outcome
    finally:
        lock.__exit__(None, None, None)


def recover_expired(engine, now=None, limit: int = 50) -> int:
    now = now or utcnow()
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        job_ids = list(db.scalars(select(AnalysisJob.id).where(
            AnalysisJob.kind == 'JUDGE', AnalysisJob.status == 'RUNNING',
            AnalysisJob.lease_expires_at < now).order_by(AnalysisJob.id).limit(limit)))
    recovered = 0
    for job_id in job_ids:
        if recover_job(engine, job_id, now) in {'requeued', 'failed'}:
            recovered += 1
    return recovered
