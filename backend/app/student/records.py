"""Student-facing read models: history, progress/candidates and job discovery.

All queries are scoped to the authenticated account and re-check course
membership. Filters are verified instead of silently returning an empty list,
and a student can never read another student's rows through these endpoints.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import AppError
from app.common.permissions import course_role
from app.db.base import utcnow
from app.db.models import (AnalysisJob, Assignment, AssignmentItem, AssignmentParticipant, CourseMember,
                           JudgeResult, Problem, ProblemVersion, Submission, User)
from app.judge import config as judge_config
from app.judge import results as judge_results
from app.judge.selection import Candidate, choose_best
from app.student.service import iso

DEFAULT_LIMIT = 20
MAX_LIMIT = 100


def _limit(value: int | None) -> int:
    if value is None:
        return DEFAULT_LIMIT
    return max(1, min(MAX_LIMIT, value))


def _student_courses(db: Session, user_id: int) -> list[int]:
    return list(db.scalars(select(CourseMember.course_id).where(
        CourseMember.user_id == user_id, CourseMember.status == 'ACTIVE', CourseMember.role == 'STUDENT')))


def _context() -> dict:
    mode = judge_config.execution_mode()
    return {'execution_mode': mode, 'runtime_profile': judge_config.runtime_profile(mode)}


def _in_context(result: JudgeResult | None) -> bool:
    if result is None or result.is_mock:
        return False
    mode = judge_config.execution_mode()
    if (result.execution_mode or '').upper() != mode:
        return False
    if mode == judge_config.LOCAL:
        return (result.runtime_profile or '') == judge_config.LOCAL_PROFILE
    return True


def _real_passed(result: JudgeResult | None) -> bool:
    return (_in_context(result) and result.verdict == 'ACCEPTED'
            and result.total_cases is not None and result.passed_cases == result.total_cases)


# ---------------------------------------------------------------- assignment


def assignment_view(db: Session, assignment_id: int, user: User) -> dict:
    assignment = db.get(Assignment, assignment_id)
    if assignment is None:
        raise AppError(404, 'NOT_FOUND', '资源不存在或不可访问')
    role = course_role(db, assignment.course_id, user.id)
    if role != 'TEACHER':
        participant = db.scalar(select(AssignmentParticipant).where(
            AssignmentParticipant.assignment_id == assignment.id,
            AssignmentParticipant.student_id == user.id))
        if participant is None or assignment.submission_status == 'DRAFT':
            raise AppError(404, 'NOT_FOUND', '资源不存在或不可访问')
    now = utcnow()
    items = db.execute(select(AssignmentItem, ProblemVersion, Problem)
                       .join(ProblemVersion, AssignmentItem.problem_version_id == ProblemVersion.id)
                       .join(Problem, ProblemVersion.problem_id == Problem.id)
                       .where(AssignmentItem.assignment_id == assignment.id)
                       .order_by(AssignmentItem.sort_order)).all()
    return {
        'id': str(assignment.id), 'course_id': str(assignment.course_id), 'title': assignment.title,
        'description_md': assignment.description_md, 'submission_status': assignment.submission_status,
        'submission_deadline': iso(assignment.submission_deadline),
        'submission_open': assignment.submission_status == 'OPEN' and now < assignment.submission_deadline,
        'server_time': now.isoformat(),
        'items': [{'id': str(item.id), 'title': version.title, 'question_type': problem.question_type,
                   'max_score': str(item.max_score), 'score_weight': str(item.score_weight),
                   'sort_order': item.sort_order} for item, version, problem in items],
    }


# -------------------------------------------------------------------- history


def my_submissions(db: Session, user: User, *, course_id: int | None, assignment_id: int | None,
                   assignment_item_id: int | None, language: str | None, status: str | None,
                   limit: int | None, offset: int | None) -> dict:
    courses = _student_courses(db, user.id)
    if course_id is not None:
        if course_id not in courses:
            raise AppError(404, 'NOT_FOUND', '资源不存在或不可访问')
        courses = [course_id]
    if assignment_id is not None:
        assignment = db.get(Assignment, assignment_id)
        if assignment is None or assignment.course_id not in courses:
            raise AppError(404, 'NOT_FOUND', '资源不存在或不可访问')
    if assignment_item_id is not None:
        item = db.get(AssignmentItem, assignment_item_id)
        assignment = db.get(Assignment, item.assignment_id) if item else None
        if assignment is None or assignment.course_id not in courses:
            raise AppError(404, 'NOT_FOUND', '资源不存在或不可访问')
        if assignment_id is not None and assignment.id != assignment_id:
            raise AppError(404, 'NOT_FOUND', '资源不存在或不可访问')
    if status is not None and status not in {'SUBMITTED', 'WITHDRAWN'}:
        raise AppError(422, 'VALIDATION_ERROR', '不支持的提交状态筛选', [{'field': 'status', 'type': 'invalid'}])

    statement = (select(Submission, AssignmentItem, Assignment, Problem)
                 .join(AssignmentItem, Submission.assignment_item_id == AssignmentItem.id)
                 .join(Assignment, AssignmentItem.assignment_id == Assignment.id)
                 .join(ProblemVersion, AssignmentItem.problem_version_id == ProblemVersion.id)
                 .join(Problem, ProblemVersion.problem_id == Problem.id)
                 .where(Submission.student_id == user.id, Assignment.course_id.in_(courses)))
    if assignment_id is not None:
        statement = statement.where(Assignment.id == assignment_id)
    if assignment_item_id is not None:
        statement = statement.where(AssignmentItem.id == assignment_item_id)
    if language is not None:
        statement = statement.where(Submission.language == language)
    if status is not None:
        statement = statement.where(Submission.status == status)
    total = db.scalar(select(func.count()).select_from(statement.order_by(None).subquery()))
    rows = db.execute(statement.order_by(Submission.submitted_at.desc(), Submission.id.desc())
                      .limit(_limit(limit)).offset(max(0, offset or 0))).all()
    submission_ids = [row[0].id for row in rows]
    results = {result.submission_id: result for result in db.scalars(
        select(JudgeResult).where(JudgeResult.submission_id.in_(submission_ids)))} if submission_ids else {}
    jobs = {job.submission_id: job for job in db.scalars(
        select(AnalysisJob).where(AnalysisJob.submission_id.in_(submission_ids),
                                  AnalysisJob.kind == 'JUDGE'))} if submission_ids else {}
    items = []
    for submission, item, assignment, problem in rows:
        result = results.get(submission.id)
        job = jobs.get(submission.id)
        items.append({
            'submission_id': str(submission.id), 'course_id': str(assignment.course_id),
            'assignment_id': str(assignment.id), 'assignment_title': assignment.title,
            'assignment_item_id': str(item.id),
            'title': db.scalar(select(ProblemVersion.title).where(ProblemVersion.id == item.problem_version_id)),
            'question_type': problem.question_type, 'version_no': submission.version_no,
            'submitted_at': iso(submission.submitted_at), 'language': submission.language,
            'status': submission.status, 'job_status': job.status if job else 'AWAITING_REVIEW',
            'summary': judge_results.result_view(result),
        })
    return {'items': items, 'total': total or 0, 'limit': _limit(limit), 'offset': max(0, offset or 0)}


# ------------------------------------------------------------------- progress


def course_progress(db: Session, course_id: int, user: User, *, assignment_id: int | None,
                    limit: int | None, offset: int | None) -> dict:
    if course_role(db, course_id, user.id) != 'STUDENT':
        raise AppError(403, 'STUDENT_REQUIRED', '此接口仅用于学生本人进度')
    statement = (select(AssignmentItem, Assignment, ProblemVersion, Problem)
                 .join(Assignment, AssignmentItem.assignment_id == Assignment.id)
                 .join(ProblemVersion, AssignmentItem.problem_version_id == ProblemVersion.id)
                 .join(Problem, ProblemVersion.problem_id == Problem.id)
                 .join(AssignmentParticipant, AssignmentParticipant.assignment_id == Assignment.id)
                 .where(Assignment.course_id == course_id, Assignment.submission_status != 'DRAFT',
                        AssignmentParticipant.student_id == user.id))
    if assignment_id is not None:
        statement = statement.where(Assignment.id == assignment_id)
        if db.scalar(select(Assignment.id).where(Assignment.id == assignment_id,
                                                 Assignment.course_id == course_id)) is None:
            raise AppError(404, 'NOT_FOUND', '资源不存在或不可访问')
    rows = db.execute(statement.order_by(Assignment.id, AssignmentItem.sort_order)).all()
    total = len(rows)
    page = rows[max(0, offset or 0): max(0, offset or 0) + _limit(limit)]
    item_ids = [row[0].id for row in rows]
    submissions = list(db.scalars(select(Submission).where(Submission.student_id == user.id,
                                                          Submission.assignment_item_id.in_(item_ids)))) if item_ids else []
    by_item: dict[int, list[Submission]] = {}
    for submission in submissions:
        by_item.setdefault(submission.assignment_item_id, []).append(submission)
    results = {result.submission_id: result for result in db.scalars(
        select(JudgeResult).where(JudgeResult.submission_id.in_([s.id for s in submissions])))} if submissions else {}
    jobs = {job.submission_id: job for job in db.scalars(
        select(AnalysisJob).where(AnalysisJob.submission_id.in_([s.id for s in submissions]),
                                  AnalysisJob.kind == 'JUDGE'))} if submissions else {}

    summary = {'item_count': total, 'submitted_item_count': 0, 'programming_item_count': 0,
               'passed_programming_item_count': 0, 'pending_job_count': 0, 'running_job_count': 0,
               'failed_job_count': 0}

    def evaluate(item, assignment, version, problem) -> dict:
        history = sorted(by_item.get(item.id, []), key=lambda row: (row.submitted_at, row.id), reverse=True)
        active = [row for row in history if row.status != 'WITHDRAWN']
        pending = sum(1 for row in active if jobs.get(row.id) is not None and jobs[row.id].status == 'PENDING')
        running = sum(1 for row in active if jobs.get(row.id) is not None and jobs[row.id].status == 'RUNNING')
        failed = sum(1 for row in active if jobs.get(row.id) is not None and jobs[row.id].status == 'FAILED')
        latest = active[0] if active else None
        best = None
        effective_id = latest.id if latest else None
        has_passed = None
        if problem.question_type == 'PROGRAMMING':
            candidates = [Candidate(submission_id=row.id, version_no=row.version_no,
                                    submitted_at=row.submitted_at,
                                    passed_cases=results[row.id].passed_cases,
                                    cpu_time_ms=results[row.id].cpu_time_ms,
                                    memory_kib=results[row.id].memory_kib)
                          for row in active
                          if row.id in results and _in_context(results[row.id])
                          and results[row.id].passed_cases is not None]
            chosen = choose_best(candidates)
            best = chosen.submission_id if chosen else None
            effective_id = best
            has_passed = any(_real_passed(results.get(row.id)) for row in active)
        else:
            effective_id = latest.id if latest else None
        return {
            'assignment_id': str(assignment.id), 'assignment_title': assignment.title,
            'assignment_item_id': str(item.id), 'title': version.title,
            'question_type': problem.question_type,
            'has_submitted': bool(active), 'has_passed': has_passed,
            'submission_count': len(history), 'active_submission_count': len(active),
            'pending_job_count': pending, 'running_job_count': running, 'failed_job_count': failed,
            'latest_submission_id': str(latest.id) if latest else None,
            'best_submission_id': str(best) if best else None,
            'effective_submission_id': str(effective_id) if effective_id else None,
            'has_unresolved_jobs': bool(pending or running or failed),
        }

    # The summary covers the whole filtered range; the page only shapes `items`.
    for item, assignment, version, problem in rows:
        entry = evaluate(item, assignment, version, problem)
        summary['submitted_item_count'] += 1 if entry['has_submitted'] else 0
        if problem.question_type == 'PROGRAMMING':
            summary['programming_item_count'] += 1
            summary['passed_programming_item_count'] += 1 if entry['has_passed'] else 0
        summary['pending_job_count'] += entry['pending_job_count']
        summary['running_job_count'] += entry['running_job_count']
        summary['failed_job_count'] += entry['failed_job_count']
    items = [evaluate(*row) for row in page]

    return {'items': items, 'total': total, 'limit': _limit(limit), 'offset': max(0, offset or 0),
            'evaluation_context': _context(), 'summary': summary, 'as_of': utcnow().isoformat()}


# ------------------------------------------------------------- job discovery


def _cursor_secret() -> str:
    try:
        return Settings.load().secret
    except Exception:  # pragma: no cover - configuration failure surfaces elsewhere
        return 'cursor-fallback'


def _encode_cursor(payload: dict) -> str:
    raw = json.dumps(payload, separators=(',', ':'), sort_keys=True).encode()
    signature = hmac.new(_cursor_secret().encode(), raw, hashlib.sha256).hexdigest()[:32]
    return base64.urlsafe_b64encode(raw).decode().rstrip('=') + '.' + signature


def _decode_cursor(cursor: str, expected: dict) -> dict:
    try:
        encoded, signature = cursor.rsplit('.', 1)
        raw = base64.urlsafe_b64decode(encoded + '=' * (-len(encoded) % 4))
        if not hmac.compare_digest(hmac.new(_cursor_secret().encode(), raw, hashlib.sha256).hexdigest()[:32],
                                   signature):
            raise ValueError('bad signature')
        payload = json.loads(raw)
    except (ValueError, TypeError):
        raise AppError(422, 'INVALID_CURSOR', '查询游标无效，请重新开始扫描')
    for key, value in expected.items():
        if payload.get(key) != value:
            raise AppError(422, 'INVALID_CURSOR', '查询游标与当前筛选不匹配，请重新开始扫描')
    return payload


def _job_filters(user: User, course_id: int | None, filter_name: str | None, db: Session, columns=None):
    courses = _student_courses(db, user.id)
    if course_id is not None:
        if course_id not in courses:
            raise AppError(404, 'NOT_FOUND', '资源不存在或不可访问')
        courses = [course_id]
    statement = (select(*(columns or (AnalysisJob, Submission, AssignmentItem, Assignment, Problem)))
                 .join(Submission, Submission.id == AnalysisJob.submission_id)
                 .join(AssignmentItem, AssignmentItem.id == Submission.assignment_item_id)
                 .join(Assignment, Assignment.id == AssignmentItem.assignment_id)
                 .join(ProblemVersion, ProblemVersion.id == AssignmentItem.problem_version_id)
                 .join(Problem, Problem.id == ProblemVersion.problem_id)
                 .where(Assignment.course_id.in_(courses), Submission.student_id == user.id,
                        AnalysisJob.kind == 'JUDGE', Submission.status != 'WITHDRAWN'))
    if filter_name == 'ACTIVE':
        statement = statement.where(AnalysisJob.status.in_(['PENDING', 'RUNNING']))
    elif filter_name == 'FAILED':
        statement = statement.where(AnalysisJob.status == 'FAILED')
    return statement


def _job_item(job: AnalysisJob, submission: Submission, item: AssignmentItem, assignment: Assignment,
              problem: Problem, now: datetime, personal_blocked: bool = False,
              service_paused: bool = False) -> dict:
    return {'submission_id': str(submission.id), 'assignment_id': str(assignment.id),
            'assignment_item_id': str(item.id), 'question_type': problem.question_type,
            'version_no': submission.version_no, 'submitted_at': iso(submission.submitted_at),
            'job': judge_results.job_view(job, now, personal_blocked, service_paused)}


def my_judge_jobs(db: Session, user: User, *, course_id: int | None, filter_name: str | None,
                  limit: int | None, offset: int | None, cursor: str | None) -> dict:
    now = utcnow()
    personal_blocked, service_paused = judge_results.dispatch_state(db, user.id)
    filter_name = (filter_name or 'ACTIVE').upper()
    if filter_name == 'DISCOVERY':
        statement = _job_filters(user, course_id, None, db)
        expected = {'user': user.id, 'course': course_id, 'filter': 'DISCOVERY'}
        if cursor:
            payload = _decode_cursor(cursor, expected)
            high_watermark = int(payload['high_watermark'])
            last_id = int(payload['last_id'])
        else:
            id_statement = _job_filters(user, course_id, None, db, columns=(AnalysisJob.id,))
            high_watermark = db.scalar(select(func.max(id_statement.subquery().c.id))) or 0
            last_id = 0
        page_size = min(MAX_LIMIT, max(1, limit or MAX_LIMIT))
        rows = db.execute(statement.where(AnalysisJob.id > last_id, AnalysisJob.id <= high_watermark)
                          .order_by(AnalysisJob.id).limit(page_size)).all()
        items = [_job_item(job, submission, item, assignment, problem, now, personal_blocked, service_paused)
                 for job, submission, item, assignment, problem in rows]
        next_cursor = None
        has_more = len(items) == page_size and bool(items)
        if items:
            next_cursor = _encode_cursor({**expected, 'high_watermark': high_watermark,
                                          'last_id': rows[-1][0].id})
        return {'items': items, 'next_cursor': next_cursor, 'has_more': has_more,
                'scan_high_watermark': high_watermark}
    if filter_name not in {'ACTIVE', 'FAILED'}:
        raise AppError(422, 'VALIDATION_ERROR', '不支持的任务筛选', [{'field': 'filter', 'type': 'invalid'}])
    statement = _job_filters(user, course_id, filter_name, db)
    total = db.scalar(select(func.count()).select_from(statement.order_by(None).subquery()))
    rows = db.execute(statement.order_by(AnalysisJob.id.desc()).limit(_limit(limit))
                      .offset(max(0, offset or 0))).all()
    return {'items': [_job_item(job, submission, item, assignment, problem, now, personal_blocked, service_paused)
                      for job, submission, item, assignment, problem in rows],
            'total': total or 0, 'limit': _limit(limit), 'offset': max(0, offset or 0)}


def batch_status(db: Session, user: User, submission_ids: list[str]) -> dict:
    if not 1 <= len(submission_ids) <= MAX_LIMIT:
        raise AppError(422, 'VALIDATION_ERROR', '每次需查询 1～100 份提交',
                       [{'field': 'submission_ids', 'type': 'invalid'}])
    if len(set(submission_ids)) != len(submission_ids):
        raise AppError(422, 'VALIDATION_ERROR', '提交标识不能重复',
                       [{'field': 'submission_ids', 'type': 'invalid'}])
    try:
        ids = [int(value) for value in submission_ids]
    except ValueError:
        raise AppError(404, 'NOT_FOUND', '资源不存在或不可访问')
    rows = db.execute(select(Submission, AnalysisJob, JudgeResult)
                      .outerjoin(AnalysisJob, (AnalysisJob.submission_id == Submission.id)
                                 & (AnalysisJob.kind == 'JUDGE'))
                      .outerjoin(JudgeResult, JudgeResult.submission_id == Submission.id)
                      .where(Submission.id.in_(ids), Submission.student_id == user.id)).all()
    if len(rows) != len(ids):
        raise AppError(404, 'NOT_FOUND', '资源不存在或不可访问')
    now = utcnow()
    personal_blocked, service_paused = judge_results.dispatch_state(db, user.id)
    items = [{'submission_id': str(submission.id), 'status': submission.status,
              'job': judge_results.job_view(job, now, personal_blocked, service_paused) if job else None,
              'result': judge_results.result_view(result)} for submission, job, result in rows]
    return {'items': items}
