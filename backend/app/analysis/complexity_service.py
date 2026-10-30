"""Complexity analysis: eligibility, request state machine and report projection.

The worker claims a ``PENDING`` report, marks it ``RUNNING`` with a lease, runs
the trace collection outside the transaction, and writes the result only if the
lease is still held. That is the same fencing discipline the judge uses, so a
late worker cannot overwrite a result that a retry already produced.

Only the measurement step changed with the trace-based rebuild: the state
machine, eligibility rules, batch queue and teacher projection are the same
ones the wall-clock implementation used. A submission whose language has no
trace adapter (Java on this node) is rejected with a stated reason instead of
being given a lexical guess.
"""
from __future__ import annotations

import json
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.analysis.trace import collect as trace_collect
from app.analysis.trace import infer as trace_infer
from app.analysis.trace import report as trace_report
from app.common.permissions import course_role, require_teacher
from app.core.errors import AppError
from app.db.base import utcnow
from app.db.models import (Assignment, AssignmentItem, ComplexityReport, JudgeResult,
                           Problem, ProblemComplexityProfile, ProblemVersion, Submission, User)
from app.judge import config as judge_config

IMPLEMENTATION_NAME = 'complexity_trace'
IMPLEMENTATION_VERSION = '1'
LEASE_SECONDS = 180
# Counting is cheap compared with the old wall-clock ladder; the budget mostly
# guards against a pathological submission.
TRACE_BUDGET_MS = 60_000


class Ineligible(Exception):
    """The submission cannot be analysed; the reason is part of the contract."""

    def __init__(self, code: str, message: str, details: dict | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details


def eligibility(db: Session, submission: Submission, item: AssignmentItem,
                problem: Problem) -> tuple[bool, str | None, dict]:
    """Decide whether a submission may be analysed, with a stated reason.

    Only a *really* accepted submission qualifies: not a mock verdict, not a
    partial pass, and judged under the execution context currently configured.
    Analysing a failed program would describe a program that does not solve the
    problem, which is not what the feature promises.

    A language without a trace adapter is rejected here rather than producing a
    report with a structural guess: the feature now promises counts from a real
    execution or an explicit statement that it cannot conclude.
    """
    if item is None or problem is None:
        return False, 'NOT_FOUND', {}
    if submission.status == 'WITHDRAWN':
        return False, 'SUBMISSION_WITHDRAWN', {}
    if problem.question_type != 'PROGRAMMING':
        return False, 'NOT_A_PROGRAMMING_ITEM', {}
    result = db.scalar(select(JudgeResult).where(JudgeResult.submission_id == submission.id))
    if result is None:
        return False, 'NOT_JUDGED_YET', {}
    if result.is_mock:
        return False, 'MOCK_RESULT_NOT_ANALYSABLE', {'verdict': result.verdict}
    if result.verdict != 'ACCEPTED':
        return False, 'SUBMISSION_NOT_ACCEPTED', {'verdict': result.verdict}
    if not (result.total_cases and result.passed_cases == result.total_cases):
        return False, 'SUBMISSION_NOT_ACCEPTED', {'verdict': result.verdict}
    mode = judge_config.execution_mode()
    if (result.execution_mode or '').upper() != mode or result.runtime_profile != judge_config.runtime_profile(mode):
        return False, 'JUDGE_CONTEXT_CHANGED', {'execution_mode': result.execution_mode}
    if not judge_config.driver_available(mode):
        return False, 'JUDGE_CONFIGURATION_UNSUPPORTED', {'execution_mode': mode}
    if judge_config.toolchain(submission.language) is None:
        return False, 'UNSUPPORTED_LANGUAGE', {'language': submission.language}
    if not trace_collect.supports_language(submission.language):
        return False, 'NO_TRACE_ADAPTER', {'language': submission.language}
    return True, None, {'verdict': result.verdict, 'execution_mode': result.execution_mode,
                        'runtime_profile': result.runtime_profile}


def profile_for(db: Session, version_id: int) -> ProblemComplexityProfile | None:
    return db.scalar(select(ProblemComplexityProfile).where(
        ProblemComplexityProfile.problem_version_id == version_id))


def _retry_failed_report(db, report, actor, request_id):
    history=list(report.history or [])
    if any(h.get('request_id')==request_id and h.get('request_actor')==str(actor.id) for h in history):
        return False
    if report.status not in ('FAILED','INELIGIBLE'):return False
    if report.attempt_no>=3:
        raise AppError(409,'COMPLEXITY_RETRY_LIMIT','本版本分析已尝试3次，请联系教师检查配置')
    report.history=[*history,dict(event='EXPLICIT_RETRY',request_id=request_id,request_actor=str(actor.id),
        status=report.status,error=report.error_message,summary=report.summary,trace_meta=report.trace_meta,
        trace_series=report.trace_series,time_class=report.time_class,space_class=report.space_class,
        implementation_name=report.implementation_name,implementation_version=report.implementation_version,
        finished_at=report.finished_at.isoformat() if report.finished_at else None)]
    report.status='PENDING';report.requested_by=actor.id;report.requested_at=utcnow()
    report.finished_at=None;report.lease_expires_at=None;report.error_message=None
    report.time_class=None;report.space_class=None;report.time_confidence=None;report.space_confidence=None;report.time_source=None
    report.summary={};report.trace_meta={};report.trace_series={};report.limitations=[]
    db.flush();return True


def request_report(db: Session, submission_id: int, actor: User,
                   client_request_id: str) -> dict:
    """Idempotent report creation; a new explicit command may retry a failed report.

    ``client_request_id`` is accepted for compatibility with the other write
    endpoints, successful/running reports are structurally unique by submission. Replaying
    a request does not rerun it; a fresh request may retry an eligible FAILED or
    INELIGIBLE report up to three attempts, preserving history.
    """
    submission = db.scalar(select(Submission).where(Submission.id == submission_id).with_for_update())
    if submission is None:
        raise AppError(404, 'NOT_FOUND', '资源不存在或不可访问')
    item = db.get(AssignmentItem, submission.assignment_item_id)
    assignment = db.get(Assignment, item.assignment_id) if item else None
    if item is None or assignment is None:
        raise AppError(404, 'NOT_FOUND', '资源不存在或不可访问')
    role = course_role(db, assignment.course_id, actor.id)
    if role not in ('STUDENT', 'TEACHER'):
        raise AppError(404, 'NOT_FOUND', '资源不存在或不可访问')
    if role == 'STUDENT' and submission.student_id != actor.id:
        raise AppError(404, 'NOT_FOUND', '资源不存在或不可访问')
    version = db.get(ProblemVersion, item.problem_version_id)
    problem = db.get(Problem, version.problem_id) if version else None
    allowed, reason, details = eligibility(db, submission, item, problem)
    if not allowed:
        raise AppError(409, reason, _reason_message(reason), details)
    existing = db.scalar(select(ComplexityReport).where(ComplexityReport.submission_id == submission.id))
    if existing is not None:
        if existing.implementation_name != IMPLEMENTATION_NAME \
                or existing.implementation_version != IMPLEMENTATION_VERSION:
            # A new implementation must produce a new report rather than silently
            # mixing two methods under one row. The superseded conclusion is kept
            # in history: a teacher who read the old verdict can see it changed.
            if existing.status in ('SUCCEEDED', 'NOT_MEASURABLE'):
                existing.history = [* (existing.history or []), {
                    'implementation_name': existing.implementation_name,
                    'implementation_version': existing.implementation_version,
                    'status': existing.status,
                    'time_class': existing.time_class,
                    'space_class': existing.space_class,
                    'summary': existing.summary,
                    'finished_at': existing.finished_at.isoformat()
                    if existing.finished_at else None,
                }]
            existing.implementation_name = IMPLEMENTATION_NAME
            existing.implementation_version = IMPLEMENTATION_VERSION
            existing.status = 'PENDING'
            # The verdict columns belong to the superseded run; a queued row must
            # not keep publishing the old class.
            existing.time_class = None
            existing.space_class = None
            existing.time_confidence = None
            existing.space_confidence = None
            existing.time_source = None
            existing.summary = {}
            existing.trace_meta = {}
            existing.trace_series = {}
            existing.limitations = []
            existing.error_message = None
            existing.finished_at = None
            existing.lease_expires_at = None
            existing.attempt_no = 0
            existing.requested_by = actor.id
            existing.requested_at = utcnow()
            db.commit()
            return report_view(db, submission.id, actor)
        _retry_failed_report(db,existing,actor,client_request_id)
        db.commit()
        return report_view(db, submission.id, actor)
    profile = profile_for(db, item.problem_version_id)
    report = ComplexityReport(
        submission_id=submission.id, assignment_item_id=item.id, student_id=submission.student_id,
        status='PENDING', language=submission.language,
        trace_meta={'profile_family': profile.family if profile else None},
        trace_series={}, summary={}, limitations=[],
        implementation_name=IMPLEMENTATION_NAME,
        implementation_version=IMPLEMENTATION_VERSION, requested_by=actor.id,
        requested_at=utcnow(), attempt_no=0,history=[dict(event='REQUESTED',request_id=client_request_id,request_actor=str(actor.id))])
    db.add(report)
    db.commit()
    return report_view(db, submission.id, actor)


def _reason_message(code: str | None) -> str:
    return {
        'NOT_FOUND': '资源不存在或不可访问',
        'SUBMISSION_WITHDRAWN': '已撤回的提交不参与复杂度分析',
        'NOT_A_PROGRAMMING_ITEM': '只有编程题可以分析复杂度',
        'NOT_JUDGED_YET': '该提交还没有评测结果，暂时无法分析复杂度',
        'MOCK_RESULT_NOT_ANALYSABLE': '模拟评测结果不参与复杂度分析，请使用真实执行结果',
        'SUBMISSION_NOT_ACCEPTED': '只有真实通过（全部测试点通过）的代码才能分析复杂度',
        'JUDGE_CONTEXT_CHANGED': '该结果来自不同的执行环境，请用当前环境重新评测',
        'JUDGE_CONFIGURATION_UNSUPPORTED': '当前评测节点不支持真实执行',
        'UNSUPPORTED_LANGUAGE': '当前节点不支持该提交语言',
        'NO_TRACE_ADAPTER': '该语言暂不支持执行轨迹采集，无法分析复杂度（当前支持 Python、C、C++）',
    }.get(code, '该提交不满足复杂度分析条件')


def visible_report(db: Session, submission_id: int, actor: User) -> tuple[ComplexityReport | None, dict]:
    submission = db.get(Submission, submission_id)
    if submission is None:
        raise AppError(404, 'NOT_FOUND', '资源不存在或不可访问')
    item = db.get(AssignmentItem, submission.assignment_item_id)
    assignment = db.get(Assignment, item.assignment_id) if item else None
    if item is None or assignment is None:
        raise AppError(404, 'NOT_FOUND', '资源不存在或不可访问')
    role = course_role(db, assignment.course_id, actor.id)
    if role == 'STUDENT' and submission.student_id != actor.id:
        raise AppError(404, 'NOT_FOUND', '资源不存在或不可访问')
    report = db.scalar(select(ComplexityReport).where(ComplexityReport.submission_id == submission_id))
    return report, {'course_id': assignment.course_id, 'role': role, 'submission': submission,
                    'item': item, 'assignment': assignment}


def report_view(db: Session, submission_id: int, actor: User) -> dict:
    report, context = visible_report(db, submission_id, actor)
    submission = context['submission']
    if report is None:
        return {'submission_id': str(submission_id), 'status': 'NONE', 'report': None,
                'reason': None, 'eligible': None}
    payload = report_payload(report)
    return {'submission_id': str(submission_id), 'status': report.status,
            'eligible': report.status not in ('INELIGIBLE',), 'report': payload,
            'reason': report.error_message if report.status in ('INELIGIBLE', 'NOT_MEASURABLE',
                                                                'FAILED') else None}


def report_payload(report: ComplexityReport) -> dict | None:
    if report.status in ('PENDING', 'RUNNING'):
        return None
    summary = report.summary or {}
    return {
        'status': report.status,
        'language': report.language,
        'implementation_name': report.implementation_name,
        'implementation_version': report.implementation_version,
        'time': summary.get('time', {}),
        'space': summary.get('space', {}),
        'trace': report.trace_series or {},
        'trace_meta': report.trace_meta or {},
        'limitations': report.limitations or [],
        'error': report.error_message,
        'requested_at': report.requested_at.isoformat() if report.requested_at else None,
        'finished_at': report.finished_at.isoformat() if report.finished_at else None,
    }


def batch_request(db: Session, course_id: int, actor: User, body: dict) -> dict:
    """Queue analysis for every really accepted submission of one item.

    A 60-student class is the main use case of this feature, and clicking each
    submission once is not usable. Idempotent by construction: a submission that
    already has a report is skipped, so re-posting returns the current state.
    """
    require_teacher(db, course_id, actor.id)
    item_id = int(body['assignment_item_id'])
    item = db.get(AssignmentItem, item_id)
    assignment = db.get(Assignment, item.assignment_id) if item else None
    if item is None or assignment is None or assignment.course_id != course_id:
        raise AppError(404, 'NOT_FOUND', '资源不存在或不可访问')
    version = db.get(ProblemVersion, item.problem_version_id)
    problem = db.get(Problem, version.problem_id) if version else None
    rows = db.execute(
        select(Submission, JudgeResult)
        .join(JudgeResult, JudgeResult.submission_id == Submission.id)
        .where(Submission.assignment_item_id == item_id,
               Submission.status == 'SUBMITTED')
        .order_by(Submission.student_id, Submission.submitted_at, Submission.id)).all()
    latest: dict[int, tuple] = {}
    for submission, result in rows:
        latest[submission.student_id] = (submission, result)
    queued = 0
    skipped = 0
    ineligible = 0
    reasons: dict[str, int] = {}
    for student_id in sorted(latest):
        submission, result = latest[student_id]
        allowed, reason, _details = _eligibility_from_result(
            submission, item, problem, result)
        if not allowed:
            ineligible += 1
            reasons[reason] = reasons.get(reason, 0) + 1
            continue
        existing = db.scalar(select(ComplexityReport).where(
            ComplexityReport.submission_id == submission.id))
        if existing is not None:
            skipped += 1
            continue
        db.add(ComplexityReport(
            submission_id=submission.id, assignment_item_id=item_id,
            student_id=student_id, status='PENDING', language=submission.language,
            trace_meta={}, trace_series={}, summary={}, limitations=[],
            implementation_name=IMPLEMENTATION_NAME,
            implementation_version=IMPLEMENTATION_VERSION, requested_by=actor.id,
            requested_at=utcnow(), attempt_no=0))
        queued += 1
    db.commit()
    return {'assignment_item_id': str(item_id), 'queued': queued, 'skipped': skipped,
            'ineligible': ineligible, 'ineligible_reasons': reasons}


def _eligibility_from_result(submission: Submission, item, problem,
                             result: JudgeResult) -> tuple[bool, str | None, dict]:
    """Eligibility for a row already joined with its judge result (batch path)."""
    if item is None or problem is None:
        return False, 'NOT_FOUND', {}
    if submission.status == 'WITHDRAWN':
        return False, 'SUBMISSION_WITHDRAWN', {}
    if problem.question_type != 'PROGRAMMING':
        return False, 'NOT_A_PROGRAMMING_ITEM', {}
    if result is None:
        return False, 'NOT_JUDGED_YET', {}
    if result.is_mock:
        return False, 'MOCK_RESULT_NOT_ANALYSABLE', {}
    if result.verdict != 'ACCEPTED' or not (
            result.total_cases and result.passed_cases == result.total_cases):
        return False, 'SUBMISSION_NOT_ACCEPTED', {}
    mode = judge_config.execution_mode()
    if (result.execution_mode or '').upper() != mode or result.runtime_profile != judge_config.runtime_profile(mode):
        return False, 'JUDGE_CONTEXT_CHANGED', {}
    if not judge_config.driver_available(mode):
        return False, 'JUDGE_CONFIGURATION_UNSUPPORTED', {}
    if judge_config.toolchain(submission.language) is None:
        return False, 'UNSUPPORTED_LANGUAGE', {}
    if not trace_collect.supports_language(submission.language):
        return False, 'NO_TRACE_ADAPTER', {}
    return True, None, {}


# ------------------------------------------------------------------- worker


def claim(db: Session) -> ComplexityReport | None:
    mode=judge_config.execution_mode()
    report = db.scalar(select(ComplexityReport).join(JudgeResult,JudgeResult.submission_id==ComplexityReport.submission_id)
                       .where(ComplexityReport.status == 'PENDING',JudgeResult.is_mock.is_(False),
                              JudgeResult.execution_mode==mode,JudgeResult.runtime_profile==judge_config.runtime_profile(mode))
                       .order_by(ComplexityReport.id)
                       .with_for_update(of=ComplexityReport,skip_locked=True).limit(1))
    if report is None:
        db.commit()
        return None
    report.status = 'RUNNING'
    report.attempt_no += 1
    report.started_at = utcnow()
    report.lease_expires_at = report.started_at + timedelta(seconds=LEASE_SECONDS)
    db.info['complexity_claim']=(report.id,report.attempt_no,report.started_at)
    db.commit()
    return report


def recover_expired(db: Session) -> int:
    now = utcnow()
    count = 0
    for report in db.scalars(select(ComplexityReport).where(
            ComplexityReport.status == 'RUNNING', ComplexityReport.lease_expires_at <= now)
            .with_for_update(skip_locked=True)):
        report.status = 'FAILED'
        report.error_message = 'LEASE_EXPIRED: 分析超时，请重新请求'
        report.finished_at = now
        report.lease_expires_at = None
        count += 1
    db.commit()
    return count


def process_one(db: Session, *, measure: bool = True) -> bool:
    """Analyse one pending report. Returns False when the queue is empty."""
    recover_expired(db)
    report = claim(db)
    if report is None:
        return False
    report_id = report.id
    try:
        _analyse(db, report_id, measure=measure)
    except Exception as error:  # noqa: BLE001 - converted to a stored failure
        db.rollback()
        _fail(db, report_id, f'{type(error).__name__}: {error}'[:400])
    return True


def _analyse(db: Session, report_id: int, *, measure: bool) -> None:
    report = db.get(ComplexityReport, report_id)
    if report is None:
        return
    submission = db.get(Submission, report.submission_id)
    item = db.get(AssignmentItem, report.assignment_item_id)
    version = db.get(ProblemVersion, item.problem_version_id) if item else None
    problem = db.get(Problem, version.problem_id) if version else None
    if submission is None or item is None or problem is None:
        _fail(db, report_id, '来源提交已不可用')
        return
    allowed, reason, _details = eligibility(db, submission, item, problem)
    if not allowed:
        _write_plain(db, report_id, status='INELIGIBLE', error_message=_reason_message(reason),
                     limitations=[])
        return
    language = submission.language or 'python3'
    profile = profile_for(db, version.id)
    if not measure:
        _write_plain(db, report_id, status='NOT_MEASURABLE',
                     error_message='本次请求没有执行轨迹采集，报告不给出复杂度结论',
                     limitations=[])
        return
    if profile is None:
        _write_plain(db, report_id, status='NOT_MEASURABLE',
                     error_message='该题尚未配置可伸缩的输入形态，无法采集执行轨迹，'
                                   '因此不给出复杂度结论',
                     limitations=['没有可伸缩输入就没有执行轨迹，本报告不做推测'],
                     trace_meta={'profile_family': None})
        return
    if profile.family == 'FIXED':
        _write_plain(db, report_id, status='NOT_MEASURABLE',
                     error_message='该题输入规模固定（没有可伸缩的规模参数），'
                                   '复杂度描述的是这个固定输入下的代价，无法测量增长',
                     limitations=['固定输入下的复杂度不随 n 变化，平台不报告增长类别'],
                     trace_meta={'profile_family': profile.family})
        return
    if profile.family == 'EXISTING_CASES':
        detail = (profile.spec or {}).get('reason') or '该题的生成输入没有通过验收'
        _write_plain(db, report_id, status='NOT_MEASURABLE',
                     error_message=f'该题没有可用的可伸缩输入：{detail}',
                     limitations=['没有可伸缩输入就没有执行轨迹，本报告不做推测'],
                     trace_meta={'profile_family': profile.family})
        return
    language_label = trace_collect.language_label(language)
    ladder = trace_collect.collect(submission.content, language, profile.family,
                                   profile.spec or {}, seed=report.id,
                                   budget_ms=TRACE_BUDGET_MS)
    if not ladder.ok_points:
        detail = next((point.detail for point in ladder.points if point.detail), None)
        _fail(db, report_id,
              f'在合成输入上无法完成轨迹采集（{ladder.stop_reason}）：{detail or "没有完成的档位"}')
        return
    conclusion = trace_infer.infer(ladder, language_label=language_label)
    payload = trace_report.build(ladder, conclusion, language=language,
                                 language_label=language_label,
                                 profile_family=profile.family)
    summary = payload['summary']
    _write(db, report_id, status='SUCCEEDED', summary=summary,
           trace_meta=payload['trace_meta'], trace_series=payload['trace_series'],
           limitations=payload['limitations'],
           time_class=summary['time']['class'],
           space_class=summary['space']['class'],
           time_confidence=summary['time']['confidence'],
           space_confidence=summary['space']['confidence'],
           time_source='TRACE')


def _write_plain(db: Session, report_id: int, **values) -> None:
    values.setdefault('summary', {})
    values.setdefault('trace_meta', {})
    values.setdefault('trace_series', {})
    _write(db, report_id, **values)


def _write(db: Session, report_id: int, **values) -> None:
    report = db.scalar(select(ComplexityReport).where(ComplexityReport.id == report_id)
                       .with_for_update().execution_options(populate_existing=True))
    ticket=db.info.get('complexity_claim')
    if report is None or report.status not in ('RUNNING',) or ticket!=(report.id,report.attempt_no,report.started_at):
        db.rollback()
        return
    if report.lease_expires_at is not None and report.lease_expires_at <= utcnow():
        db.rollback()
        return
    for key, value in values.items():
        setattr(report, key, value)
    report.finished_at = utcnow()
    report.lease_expires_at = None
    db.commit()


def _fail(db: Session, report_id: int, message: str) -> None:
    try:
        _write(db, report_id, status='FAILED', error_message=message,
               summary={}, trace_meta={}, trace_series={})
    except Exception:  # pragma: no cover - the row is already gone or locked
        db.rollback()


# ---------------------------------------------------------------- teacher view


def course_overview(db: Session, course_id: int, actor: User, *,
                    assignment_item_id: int | None = None,
                    limit: int = 100) -> dict:
    """Class-level table of the latest complexity report per student.

    The teacher sees the merged verdict, not raw measurements: the point of the
    overview is "who is quadratic where", and the per-submission endpoint holds
    the detail.
    """
    require_teacher(db, course_id, actor.id)
    query = (select(ComplexityReport, Submission, User)
             .join(Submission, Submission.id == ComplexityReport.submission_id)
             .join(User, User.id == ComplexityReport.student_id)
             .join(AssignmentItem, AssignmentItem.id == ComplexityReport.assignment_item_id)
             .join(Assignment, Assignment.id == AssignmentItem.assignment_id)
             .where(Assignment.course_id == course_id))
    if assignment_item_id is not None:
        item = db.get(AssignmentItem, assignment_item_id)
        assignment = db.get(Assignment, item.assignment_id) if item else None
        if item is None or assignment is None or assignment.course_id != course_id:
            raise AppError(404, 'NOT_FOUND', '资源不存在或不可访问')
        query = query.where(ComplexityReport.assignment_item_id == assignment_item_id)
    rows = db.execute(query.order_by(ComplexityReport.student_id, ComplexityReport.id)).all()
    latest: dict[tuple[int, int], tuple] = {}
    for report, submission, user in rows:
        latest[(report.student_id, report.assignment_item_id)] = (report, submission, user)
    items = []
    for (_, _), (report, submission, user) in sorted(latest.items()):
        version = db.get(ProblemVersion, db.get(AssignmentItem, report.assignment_item_id).problem_version_id)
        items.append({
            'student_id': str(user.id), 'student_no': user.student_no,
            'name': user.full_name,
            'assignment_item_id': str(report.assignment_item_id),
            'title': version.title if version else None,
            'submission_id': str(submission.id), 'status': report.status,
            'time_class': report.time_class, 'space_class': report.space_class,
            'time_confidence': report.time_confidence, 'time_source': report.time_source,
            'requested_at': report.requested_at.isoformat() if report.requested_at else None,
        })
    items.sort(key=lambda row: (row['assignment_item_id'], row['student_no'] or '', row['student_id']))
    return {'items': items[:limit], 'total': len(items)}


def items_with_profiles(db: Session, course_id: int, actor: User,
                        assignment_id: int | None = None) -> list[dict]:
    """Programming items of a course plus whether a scale profile exists."""
    require_teacher(db, course_id, actor.id)
    query = (select(AssignmentItem, ProblemVersion, Problem, Assignment)
             .join(Assignment, Assignment.id == AssignmentItem.assignment_id)
             .join(ProblemVersion, ProblemVersion.id == AssignmentItem.problem_version_id)
             .join(Problem, Problem.id == ProblemVersion.problem_id)
             .where(Assignment.course_id == course_id, Problem.question_type == 'PROGRAMMING'))
    if assignment_id is not None:
        query = query.where(Assignment.id == assignment_id)
    rows = db.execute(query.order_by(Assignment.id, AssignmentItem.sort_order)).all()
    profiles = {profile.problem_version_id: profile for profile in db.scalars(
        select(ProblemComplexityProfile).where(
            ProblemComplexityProfile.problem_version_id.in_([row[1].id for row in rows])))} if rows else {}
    return [{'item_id': str(item.id), 'assignment_id': str(assignment.id),
             'assignment_title': assignment.title, 'problem_code': problem.code,
             'title': version.title,
             'profile_family': profiles[version.id].family if version.id in profiles else None}
            for item, version, problem, assignment in rows]


def pending_count(db: Session) -> int:
    return db.scalar(select(func.count()).select_from(ComplexityReport).where(
        ComplexityReport.status.in_(['PENDING', 'RUNNING']))) or 0


def parse_spec(raw: str | None) -> dict:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except ValueError as error:
        raise ValueError('伸缩档 spec 必须是合法 JSON') from error
    if not isinstance(value, dict):
        raise ValueError('伸缩档 spec 必须是 JSON 对象')
    return value
