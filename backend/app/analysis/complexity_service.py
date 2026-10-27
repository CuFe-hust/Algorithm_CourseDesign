"""Complexity analysis: eligibility, request state machine and report projection.

The worker claims a ``PENDING`` report, marks it ``RUNNING`` with a lease, runs
the measurement outside the transaction, and writes the result only if the lease
is still held. That is the same fencing discipline the judge uses, so a late
worker cannot overwrite a result that a retry already produced.
"""
from __future__ import annotations

import json
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.analysis.algorithms import complexity as engine
from app.analysis import probe
from app.common.permissions import course_role, require_teacher
from app.core.errors import AppError
from app.db.base import utcnow
from app.db.models import (Assignment, AssignmentItem, ComplexityReport, JudgeResult,
                           Problem, ProblemComplexityProfile, ProblemVersion, Submission, User)
from app.judge import config as judge_config

IMPLEMENTATION_NAME = 'complexity_probe'
IMPLEMENTATION_VERSION = '1'
LEASE_SECONDS = 180
MEASURE_BUDGET_MS = 150_000
MEASURE_WALL_LIMIT_MS = 10_000
MEASURE_REPEATS = 3


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
    if (result.execution_mode or '').upper() != mode:
        return False, 'JUDGE_CONTEXT_CHANGED', {'execution_mode': result.execution_mode}
    if not judge_config.driver_available(mode):
        return False, 'JUDGE_CONFIGURATION_UNSUPPORTED', {'execution_mode': mode}
    if judge_config.toolchain(submission.language) is None:
        return False, 'UNSUPPORTED_LANGUAGE', {'language': submission.language}
    return True, None, {'verdict': result.verdict, 'execution_mode': result.execution_mode,
                        'runtime_profile': result.runtime_profile}


def profile_for(db: Session, version_id: int) -> ProblemComplexityProfile | None:
    return db.scalar(select(ProblemComplexityProfile).where(
        ProblemComplexityProfile.problem_version_id == version_id))


def request_report(db: Session, submission_id: int, actor: User,
                   client_request_id: str) -> dict:
    """Idempotent creation of one report per submission.

    ``client_request_id`` is accepted for compatibility with the other write
    endpoints, but the real idempotency key is the submission itself: asking
    twice for the same submission returns the existing report instead of running
    the program twice.
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
            # mixing two methods under one row.
            existing.implementation_name = IMPLEMENTATION_NAME
            existing.implementation_version = IMPLEMENTATION_VERSION
            existing.status = 'PENDING'
            existing.error_message = None
            existing.finished_at = None
            existing.attempt_no = 0
            existing.requested_by = actor.id
            existing.requested_at = utcnow()
            db.commit()
            return report_view(db, submission.id, actor)
        db.commit()
        return report_view(db, submission.id, actor)
    profile = profile_for(db, item.problem_version_id)
    report = ComplexityReport(
        submission_id=submission.id, assignment_item_id=item.id, student_id=submission.student_id,
        status='PENDING', language=submission.language, growth={},
        summary={}, limitations=[], implementation_name=IMPLEMENTATION_NAME,
        implementation_version=IMPLEMENTATION_VERSION, requested_by=actor.id,
        requested_at=utcnow(), attempt_no=0,
        static_analysis={'profile_family': profile.family if profile else None})
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
            'reason': report.error_message if report.status in ('INELIGIBLE', 'FAILED') else None}


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
        'static': report.static_analysis or {},
        'dynamic': report.growth or {},
        'limitations': report.limitations or [],
        'error': report.error_message,
        'requested_at': report.requested_at.isoformat() if report.requested_at else None,
        'finished_at': report.finished_at.isoformat() if report.finished_at else None,
    }


# ------------------------------------------------------------------- worker


def claim(db: Session) -> ComplexityReport | None:
    report = db.scalar(select(ComplexityReport)
                       .where(ComplexityReport.status == 'PENDING')
                       .order_by(ComplexityReport.id)
                       .with_for_update(skip_locked=True).limit(1))
    if report is None:
        db.commit()
        return None
    report.status = 'RUNNING'
    report.attempt_no += 1
    report.started_at = utcnow()
    report.lease_expires_at = report.started_at + timedelta(seconds=LEASE_SECONDS)
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
    allowed, reason, details = eligibility(db, submission, item, problem)
    if not allowed:
        _write(db, report_id, status='INELIGIBLE', error_message=_reason_message(reason),
               summary={}, static_analysis={}, growth={}, limitations=[])
        return
    language = submission.language or 'python3'
    static = engine.analyze_static(submission.content, language)
    profile = profile_for(db, version.id)
    limitations = [
        '输入由平台按题目伸缩档合成，覆盖常见规模，不代表最坏情况或全部合法输入',
        '静态分析依据代码结构，等价改写可能改变结论',
    ]
    if static.language_family == 'c-like':
        limitations.append('该语言没有语法树分析，静态结论来自词法结构，置信度低')
    dynamic_payload: dict = {}
    memory_stats: dict | None = None
    if not measure:
        status = 'STATIC_ONLY'
        limitations.append('本次请求未执行测量，只给出结构分析结论')
    elif profile is None or profile.family in ('EXISTING_CASES', 'FIXED'):
        status = 'STATIC_ONLY'
        limitations.append('该题尚未配置规模伸缩档案，无法测量增长；只给出结构分析结论')
    else:
        outcomes, stop_reason = probe.escalating_measure(
            submission.content, language, profile.family, profile.spec or {},
            seed=report.id, wall_limit_ms=MEASURE_WALL_LIMIT_MS,
            budget_ms=MEASURE_BUDGET_MS, repeats=MEASURE_REPEATS)
        raw = [engine.Measurement(n=outcome.n, wall_ms=outcome.median_ms,
                                  adjusted_ms=outcome.median_ms,
                                  peak_rss_kib=outcome.peak_rss_kib,
                                  verdict=outcome.verdict, repeats=len(outcome.walls_ms))
               for outcome in outcomes]
        reference = {outcome.n: outcome.reference_ms for outcome in outcomes
                     if outcome.reference_ms is not None}
        conclusion = engine.classify_growth(raw, reference)
        memory_stats = _memory_stats(outcomes)
        summary = engine.combine(static, conclusion, memory_stats)
        dynamic_payload = dict(conclusion.to_payload(), stop_reason=stop_reason,
                               rungs=[outcome.to_payload() for outcome in outcomes],
                               curve=engine.curve_points(
                                   conclusion.fit.fitted_class, conclusion.fit.coefficient,
                                   [outcome.n for outcome in outcomes if outcome.verdict == 'OK'],
                                   conclusion.fit.offset_ms))
        limitations.extend(summary.get('limitations', []))
        if stop_reason == 'TIME_LIMIT_EXCEEDED':
            limitations.append('最大档位触发了墙钟上限，拟合只使用未超时的档位')
        elif stop_reason in ('FLOOR_REACHED', 'NO_LADDER'):
            limitations.append('程序在可测规模内始终接近启动开销，无法据此判断增长；以结构分析为准')
        elif stop_reason == 'BUDGET_EXHAUSTED':
            limitations.append('测量预算用尽，档位数少于计划')
        _write(db, report_id, status='SUCCEEDED', summary=summary,
               static_analysis=static.to_payload(), growth=dynamic_payload,
               limitations=limitations, time_class=summary['time']['class'],
               space_class=summary['space']['class'],
               time_confidence=summary['time']['confidence'],
               space_confidence=summary['space']['confidence'],
               time_source=summary['time']['source'])
        return
    summary = engine.combine(static, engine.classify_growth([]))
    summary['limitations'] = [*limitations]
    _write(db, report_id, status=status, summary=summary,
           static_analysis=static.to_payload(), growth=dynamic_payload,
           limitations=limitations, time_class=summary['time']['class'],
           space_class=summary['space']['class'],
           time_confidence=summary['time']['confidence'],
           space_confidence=summary['space']['confidence'],
           time_source=summary['time']['source'])
    del details


def _memory_stats(outcomes) -> dict | None:
    points = [(outcome.n, outcome.peak_rss_kib) for outcome in outcomes
              if outcome.verdict == 'OK' and outcome.peak_rss_kib]
    if len(points) < 3:
        return None
    first_n, first_kib = points[0]
    last_n, last_kib = points[-1]
    if first_kib <= 0 or last_n <= first_n:
        return None
    growth = (last_kib / first_kib) / (last_n / first_n)
    space = 'O(n^2)' if growth > 1.6 else 'O(n)' if growth > 1.2 else 'O(1)'
    return {'class': space, 'growth': round(growth, 3),
            'points': [{'n': n, 'peak_rss_kib': kib} for n, kib in points]}


def _write(db: Session, report_id: int, **values) -> None:
    report = db.scalar(select(ComplexityReport).where(ComplexityReport.id == report_id)
                       .with_for_update().execution_options(populate_existing=True))
    if report is None or report.status not in ('RUNNING',):
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
        _write(db, report_id, status='FAILED', error_message=message)
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
