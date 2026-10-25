"""Result persistence, safe projection and the student rejudge entry point.

The projection is intentionally narrow: one summary per submission, no hidden
input, expected output, raw stdout/stderr or per-case rows. Compiler diagnostics
are bounded and path-sanitized before they are stored.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import limits, ratelimit
from app.core.errors import AppError
from app.db.base import utcnow
from app.db.models import (AnalysisJob, Assignment, AssignmentItem, JudgeAttempt, JudgeResult,
                           JudgeRetryRequest, Submission, TestSuite, User)
from app.judge import config, supervisor

INTERNAL_MESSAGE_LIMIT = 400


def safe_message(text: str | None, limit: int = INTERNAL_MESSAGE_LIMIT) -> str | None:
    if not text:
        return None
    cleaned = ' '.join(text.split())
    return cleaned[:limit]


def result_view(result: JudgeResult | None) -> dict | None:
    if result is None:
        return None
    return {
        'verdict': result.verdict,
        'is_mock': result.is_mock,
        'algorithm_name': result.algorithm_name,
        'algorithm_version': result.algorithm_version,
        'cpu_time_ms': result.cpu_time_ms,
        'memory_kib': result.memory_kib,
        'passed_cases': result.passed_cases,
        'executed_cases': result.executed_cases,
        'total_cases': result.total_cases,
        'execution_mode': result.execution_mode or ('MOCK' if result.is_mock else None),
        'runtime_profile': result.runtime_profile,
        'measurement_status': result.measurement_status,
        'message': safe_message(result.message) or '',
        'compiler_message': None if result.diagnostics_expired_at else result.compiler_message,
        'diagnostics_expired': result.diagnostics_expired_at is not None,
    }


def dispatch_state(db: Session, student_id: int) -> tuple[bool, bool]:
    """Return ``(personal_blocked, service_paused)`` for one student's queued work.

    ``personal_blocked`` means the student already occupies every execution slot,
    so their own PENDING job is waiting on itself rather than on node capacity.
    """
    running = db.scalar(select(func.count()).select_from(AnalysisJob)
                        .join(Submission, Submission.id == AnalysisJob.submission_id)
                        .where(Submission.student_id == student_id, AnalysisJob.kind == 'JUDGE',
                               AnalysisJob.status == 'RUNNING')) or 0
    return running >= config.per_student_concurrency(), config.service_paused()


def queue_reason(job: AnalysisJob, now: datetime, personal_blocked: bool = False,
                 service_paused: bool = False) -> str | None:
    if job.status != 'PENDING':
        return None
    available = job.available_at
    if available is not None and available > now:
        return 'RETRY_BACKOFF'
    if service_paused:
        return 'SERVICE_PAUSED'
    if personal_blocked:
        return 'PERSONAL_LIMIT'
    return 'RESOURCE_WAIT'


def job_view(job: AnalysisJob | None, now: datetime | None = None, personal_blocked: bool = False,
             service_paused: bool = False) -> dict | None:
    if job is None:
        return None
    now = now or utcnow()
    return {
        'status': job.status,
        'phase': job.phase,
        'queue_reason': queue_reason(job, now, personal_blocked, service_paused),
        'attempt_no': job.attempt_no,
        'recovery_cycle_no': job.recovery_cycle_no,
        'error_code': job.error_message if job.status == 'FAILED' else None,
        'message': safe_message(job.error_message),
    }


def attempt_view(attempt: JudgeAttempt | None) -> dict | None:
    if attempt is None:
        return None
    return {'attempt_no': attempt.attempt_no, 'status': attempt.status,
            'execution_mode': attempt.execution_mode, 'failure_code': attempt.failure_code,
            'started_at': attempt.started_at.isoformat() if attempt.started_at else None,
            'finished_at': attempt.finished_at.isoformat() if attempt.finished_at else None}


def record_success(db: Session, job_id: int, attempt_token: str, outcome, execution_mode: str,
                   runtime_profile: str, algorithm_name: str = 'local_judge',
                   algorithm_version: str = '1') -> JudgeResult | None:
    """Persist summary, attempt completion and job state in one transaction.

    Returns ``None`` when this process no longer owns the job (the conditional
    update matched nothing), in which case nothing is written.
    """
    job = db.scalar(select(AnalysisJob).where(AnalysisJob.id == job_id).with_for_update())
    if job is None or job.status != 'RUNNING' or job.attempt_token != attempt_token:
        db.rollback()
        return None
    existing = db.scalar(select(JudgeResult).where(JudgeResult.submission_id == job.submission_id))
    if existing is not None:
        db.rollback()
        return existing
    attempt = db.scalar(select(JudgeAttempt).where(JudgeAttempt.job_id == job_id,
                                                  JudgeAttempt.attempt_no == job.attempt_no))
    now = utcnow()
    measurement = ('NOT_EXECUTED' if outcome.verdict == 'COMPILATION_ERROR'
                   else 'UNAVAILABLE_LOCAL' if execution_mode == config.LOCAL else 'NOT_APPLICABLE')
    message = f'通过 {outcome.passed} / {outcome.total} 个测试点'
    result = JudgeResult(job_id=job_id, submission_id=job.submission_id, verdict=outcome.verdict,
                         is_mock=False, algorithm_name=algorithm_name,
                         algorithm_version=algorithm_version, cpu_time_ms=None, memory_kib=None,
                         message=message, passed_cases=outcome.passed, executed_cases=outcome.executed,
                         total_cases=outcome.total, attempt_id=attempt.id if attempt else None,
                         execution_mode=execution_mode, runtime_profile=runtime_profile,
                         measurement_status=measurement, compiler_message=outcome.compiler_message)
    db.add(result)
    if attempt is not None:
        attempt.status = 'SUCCEEDED'
        attempt.finished_at = now
        attempt.sandbox_ref = None
    job.status = 'SUCCEEDED'
    job.phase = 'FINISHED'
    job.finished_at = now
    job.attempt_token = None
    job.owner_id = None
    job.heartbeat_at = None
    job.lease_expires_at = None
    db.commit()
    return result


def record_failure(db: Session, job_id: int, attempt_token: str, code: str, message: str,
                   retryable: bool) -> str:
    """Mark an attempt failed and either requeue with backoff or finish as FAILED."""
    job = db.scalar(select(AnalysisJob).where(AnalysisJob.id == job_id).with_for_update())
    if job is None or job.status != 'RUNNING' or job.attempt_token != attempt_token:
        db.rollback()
        return 'lost'
    attempt = db.scalar(select(JudgeAttempt).where(JudgeAttempt.job_id == job_id,
                                                  JudgeAttempt.attempt_no == job.attempt_no))
    now = utcnow()
    if attempt is not None:
        attempt.status = 'FAILED'
        attempt.finished_at = now
        attempt.failure_code = code
        attempt.message = safe_message(message)
    job.attempt_token = None
    job.owner_id = None
    job.heartbeat_at = None
    job.lease_expires_at = None
    budget_left = retryable and job.automatic_retries_used < config.AUTO_RETRIES_PER_CYCLE
    if budget_left:
        backoff = config.AUTO_RETRY_BACKOFF[min(job.automatic_retries_used,
                                                len(config.AUTO_RETRY_BACKOFF) - 1)]
        job.automatic_retries_used += 1
        job.status = 'PENDING'
        job.phase = 'RETRY_WAIT'
        job.available_at = now + timedelta(seconds=backoff)
        job.error_message = safe_message(f'{code}: {message}')
    else:
        job.status = 'FAILED'
        job.phase = 'FINISHED'
        job.finished_at = now
        job.error_message = safe_message(f'{code}: {message}')
    db.commit()
    return 'requeued' if budget_left else 'failed'


def retry_state(db: Session, job: AnalysisJob, now: datetime | None = None) -> tuple[bool, str | None, datetime | None]:
    """Return ``(can_retry, block_reason, retry_after)`` for one failed job."""
    now = now or utcnow()
    if job.status != 'FAILED':
        return False, 'JUDGE_RETRY_NOT_ALLOWED', None
    if db.scalar(select(JudgeResult.id).where(JudgeResult.submission_id == job.submission_id)) is not None:
        return False, 'JUDGE_RETRY_NOT_ALLOWED', None
    if job.recovery_cycle_no >= limits.rejudge_max_cycles():
        return False, 'JUDGE_RETRY_BUDGET_EXHAUSTED', None
    reference = job.last_manual_retry_at or job.finished_at
    if reference is not None:
        earliest = reference + timedelta(seconds=limits.rejudge_cooldown_seconds())
        if now < earliest:
            return False, 'JUDGE_RETRY_COOLDOWN', earliest
    return True, None, None


def accept_rejudge(db: Session, submission_id: int, user: User, client_request_id: str) -> dict:
    existing = db.scalar(select(JudgeRetryRequest).where(
        JudgeRetryRequest.requested_by == user.id,
        JudgeRetryRequest.client_request_id == client_request_id))
    if existing is not None:
        if existing.submission_id != submission_id:
            raise AppError(409, 'IDEMPOTENCY_CONFLICT', '同一请求标识不能对应不同提交')
        job = db.get(AnalysisJob, existing.job_id)
        db.commit()
        return {'submission_id': str(submission_id), 'job_status': job.status if job else 'PENDING',
                'replayed': True}

    row = db.scalar(select(Submission).where(Submission.id == submission_id).with_for_update())
    if row is None:
        raise AppError(404, 'NOT_FOUND', '资源不存在或不可访问')
    item = db.get(AssignmentItem, row.assignment_item_id)
    assignment = db.get(Assignment, item.assignment_id) if item else None
    if item is None or assignment is None or row.student_id != user.id:
        raise AppError(404, 'NOT_FOUND', '资源不存在或不可访问')
    if row.status == 'WITHDRAWN':
        raise AppError(409, 'JUDGE_RETRY_NOT_ALLOWED', '已撤回的提交不能重评')
    job = db.scalar(select(AnalysisJob).where(AnalysisJob.submission_id == submission_id,
                                              AnalysisJob.kind == 'JUDGE').with_for_update())
    if job is None:
        raise AppError(409, 'JUDGE_RETRY_NOT_ALLOWED', '该提交没有可重评的评测任务')
    now = utcnow()
    allowed, reason, retry_after = retry_state(db, job, now)
    if not allowed:
        db.commit()
        if reason == 'JUDGE_RETRY_COOLDOWN' and retry_after is not None:
            raise AppError(429, 'JUDGE_RETRY_COOLDOWN', '重评冷却中，请稍后再试',
                           {'retry_after_at': retry_after.isoformat()},
                           headers={'Retry-After': str(max(1, int((retry_after - now).total_seconds())))})
        if reason == 'JUDGE_RETRY_BUDGET_EXHAUSTED':
            raise AppError(409, 'JUDGE_RETRY_BUDGET_EXHAUSTED', '累计重评次数已用尽，请联系课程管理员')
        raise AppError(409, 'JUDGE_RETRY_NOT_ALLOWED', '当前任务不接受新的重评请求')
    marker = supervisor.read_marker(job.id)
    if marker is not None:
        supervisor.terminate_marker(marker)
        supervisor.marker_path(job.id).unlink(missing_ok=True)
    ratelimit.enforce(db, 'rejudge_account', ratelimit.subject_key(str(user.id)),
                      limits.rejudge_per_hour(), 3600, code='RATE_LIMITED',
                      message='重评请求过于频繁，请稍后再试')
    parameters = dict(job.parameters or {})
    mode = str(parameters.get('execution_mode') or config.MOCK).upper()
    if mode == config.LOCAL and not parameters.get('test_suite_id'):
        raise AppError(409, 'JUDGE_CONFIGURATION_UNSUPPORTED', '运行配置不完整，请联系课程管理员')
    job.status = 'PENDING'
    job.phase = 'QUEUED'
    job.available_at = now
    job.attempt_token = None
    job.owner_id = None
    job.heartbeat_at = None
    job.lease_expires_at = None
    job.finished_at = None
    job.error_message = None
    job.automatic_retries_used = 0
    job.recovery_cycle_no += 1
    job.last_manual_retry_at = now
    db.add(JudgeRetryRequest(submission_id=submission_id, job_id=job.id, requested_by=user.id,
                             client_request_id=client_request_id,
                             recovery_cycle_no=job.recovery_cycle_no, accepted_at=now))
    db.commit()
    return {'submission_id': str(submission_id), 'job_status': 'PENDING', 'replayed': False}


def case_inputs(db: Session, suite_id: int):
    from app.judge.local import CaseInput
    from app.db.models import TestCase
    rows = db.scalars(select(TestCase).where(TestCase.test_suite_id == suite_id)
                      .order_by(TestCase.sort_order))
    return [CaseInput(sort_order=case.sort_order, input_text=case.input_text,
                      expected_output=case.expected_output) for case in rows]


def frozen_suite(db: Session, job: AnalysisJob) -> TestSuite:
    suite_id = (job.parameters or {}).get('test_suite_id')
    if suite_id is None:
        raise AppError(409, 'JUDGE_CONFIGURATION_UNSUPPORTED', '评测配置缺少测试集')
    suite = db.get(TestSuite, int(suite_id))
    if suite is None or suite.status != 'FROZEN':
        raise AppError(409, 'JUDGE_CONFIGURATION_UNSUPPORTED', '测试集快照不可用')
    return suite
