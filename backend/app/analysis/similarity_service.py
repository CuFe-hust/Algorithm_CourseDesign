"""One-step similarity batches over the submissions of a single assignment item.

This reuses the existing ``analysis_batches``/``analysis_runs``/``analysis_artifacts``
tables and the existing analysis worker instead of adding a second queue. A
``CODE_SIMILARITY`` batch contains one ``code_similarity`` run per programming
item of the requested scope, so the repository keeps a single execution model:

* scope: one assignment, optionally narrowed to one item;
* subjects: per student, the last submission before the deadline that was not
  withdrawn, exactly the snapshot rule the analysis framework already uses;
* result: pairs and clusters keyed by stable answer keys, plus a teacher
  projection that joins student number and name.

Nothing here judges plagiarism. The output is evidence attached to line ranges.
"""
from __future__ import annotations

from sqlalchemy import select

from app.analysis.framework.contracts import digest
from app.common.permissions import require_teacher
from app.core.errors import AppError
from app.db.base import utcnow
from app.db.models import (Assignment, AssignmentItem, AssignmentParticipant, Problem,
                           ProblemVersion, Submission, User)
from app.db.models.analytics import AnalysisArtifact, AnalysisBatch, AnalysisInputSnapshot, AnalysisRun

PIPELINE = 'CODE_SIMILARITY'
STEP_KEY_PREFIX = 'code_similarity@'


class SimilarityScopeError(AppError):
    pass


def _item_scope(db, course_id: int, assignment_id: int, assignment_item_id: int | None):
    assignment = db.get(Assignment, assignment_id)
    if assignment is None or assignment.course_id != course_id:
        raise AppError(404, 'NOT_FOUND', '作业不在本次课程范围')
    query = (select(AssignmentItem, ProblemVersion, Problem)
             .join(ProblemVersion, ProblemVersion.id == AssignmentItem.problem_version_id)
             .join(Problem, Problem.id == ProblemVersion.problem_id)
             .where(AssignmentItem.assignment_id == assignment.id,
                    Problem.question_type == 'PROGRAMMING'))
    if assignment_item_id is not None:
        query = query.where(AssignmentItem.id == assignment_item_id)
    rows = db.execute(query.order_by(AssignmentItem.sort_order)).all()
    if assignment_item_id is not None and not rows:
        raise AppError(404, 'NOT_FOUND', '该题不属于此作业或不是编程题')
    return assignment, rows


def _subjects(db, assignment: Assignment, item: AssignmentItem):
    """Final pre-deadline submission per student, withdrawn ones excluded."""
    participants = set(db.scalars(select(AssignmentParticipant.student_id).where(
        AssignmentParticipant.assignment_id == assignment.id)))
    rows = db.execute(
        select(Submission, User)
        .join(User, User.id == Submission.student_id)
        .where(Submission.assignment_item_id == item.id,
               Submission.status == 'SUBMITTED',
               Submission.submitted_at < assignment.submission_deadline)
        .order_by(Submission.student_id, Submission.submitted_at, Submission.id)).all()
    chosen: dict[int, tuple[Submission, User]] = {}
    for submission, user in rows:
        if submission.student_id in participants:
            chosen[submission.student_id] = (submission, user)
    return [chosen[key] for key in sorted(chosen)]


def build_payload(db, assignment: Assignment, item: AssignmentItem) -> tuple[dict, dict]:
    subjects = _subjects(db, assignment, item)
    answers = [{'answer_key': f'submission-{submission.id}', 'content': submission.content,
                'language': submission.language, 'item_key': f'item-{item.id}'}
               for submission, _ in subjects]
    people = {f'submission-{submission.id}': {'student_id': str(user.id),
                                             'student_no': user.student_no,
                                             'name': user.full_name,
                                             'version_no': submission.version_no}
              for submission, user in subjects}
    return dict(answers=answers, templates=[], comparison_scope='SAME_ITEM'), people


def create_batch(db, course_id: int, actor: User, body: dict) -> dict:
    require_teacher(db, course_id, actor.id)
    db.scalar(select(User).where(User.id == actor.id).with_for_update())
    request_hash = digest(dict(body, course_id=str(course_id), pipeline=PIPELINE))
    existing = db.scalar(select(AnalysisBatch).where(AnalysisBatch.created_by == actor.id,
                                                     AnalysisBatch.request_id == body['request_id']))
    if existing is not None:
        if existing.request_hash != request_hash:
            raise AppError(409, 'IDEMPOTENCY_CONFLICT', '同一请求标识不能对应不同分析输入')
        db.commit()
        return batch_view(db, existing.id, actor)
    assignment, rows = _item_scope(db, course_id, int(body['assignment_id']),
                                   int(body['assignment_item_id']) if body.get('assignment_item_id') else None)
    if not rows:
        raise AppError(409, 'SCOPE_REQUIRED', '该作业没有可比较的编程题')
    batch = AnalysisBatch(course_id=course_id, assignment_id=assignment.id, created_by=actor.id,
                          mode='REAL_INPUT', request_id=body['request_id'], request_hash=request_hash,
                          seed=body.get('seed', 20261028),
                          configuration={'schema_version': 'analysis-v2', 'pipeline': PIPELINE,
                                         'threshold': str(body.get('threshold', '0.5')),
                                         'assignment_item_id': (str(rows[0][0].id)
                                                                if body.get('assignment_item_id') else None)},
                          events={})
    db.add(batch)
    db.flush()
    subjects_by_item: dict[int, dict] = {}
    for item, _version, _problem in rows:
        payload, people = build_payload(db, assignment, item)
        payload['threshold'] = str(body.get('threshold', '0.5'))
        subjects_by_item[item.id] = {'people': people, 'count': len(payload['answers'])}
        snapshot = AnalysisInputSnapshot(batch_id=batch.id, scope=f'{STEP_KEY_PREFIX}{item.id}',
                                         input_hash=digest(payload), payload=payload, is_mock=False)
        db.add(snapshot)
        db.flush()
        db.add(AnalysisRun(batch_id=batch.id, step_key=f'{STEP_KEY_PREFIX}{item.id}',
                           algorithm_key='code_similarity', dependencies=[],
                           implementation_name='winnowing_token', implementation_version='2',
                           snapshot_id=snapshot.id, status='READY'))
    batch.configuration = {**batch.configuration, 'subjects': {
        str(item_id): value for item_id, value in subjects_by_item.items()}}
    db.flush()
    _refresh(db, batch)
    db.commit()
    return batch_view(db, batch.id, actor)


def _runs(db, batch_id: int) -> dict[str, AnalysisRun]:
    return {run.step_key: run for run in db.scalars(
        select(AnalysisRun).where(AnalysisRun.batch_id == batch_id).order_by(AnalysisRun.id))}


def _refresh(db, batch: AnalysisBatch) -> None:
    runs = _runs(db, batch.id)
    for run in runs.values():
        if run.status == 'WAITING_INPUT' and run.snapshot_id is not None:
            run.status = 'READY'
            run.reason = {}
    batch.status = 'COMPLETE' if all(run.status in ('SUCCEEDED', 'FAILED', 'SKIPPED', 'CANCELLED')
                                     for run in runs.values()) else 'ACTIVE'
    db.flush()


def batch_view(db, batch_id: int, actor: User) -> dict:
    batch = db.get(AnalysisBatch, batch_id)
    if batch is None:
        raise AppError(404, 'NOT_FOUND', '相似检测批次不存在')
    require_teacher(db, batch.course_id, actor.id)
    if (batch.configuration or {}).get('pipeline') != PIPELINE:
        raise AppError(404, 'NOT_FOUND', '该批次不是相似检测批次')
    runs = _runs(db, batch.id)
    artifacts = {}
    if runs:
        for artifact in db.scalars(select(AnalysisArtifact).where(
                AnalysisArtifact.run_id.in_([run.id for run in runs.values()])).order_by(AnalysisArtifact.id)):
            artifacts[artifact.run_id] = artifact
    subjects = (batch.configuration or {}).get('subjects', {})
    steps = []
    for key, run in runs.items():
        item_id = key.split('@', 1)[1]
        artifact = artifacts.get(run.id)
        steps.append({
            'item_id': item_id, 'key': key, 'status': run.status,
            'business_status': run.business_status, 'attempt_no': run.attempt_no,
            'submission_count': (subjects.get(item_id) or {}).get('count', 0),
            'implementation_name': run.implementation_name,
            'implementation_version': run.implementation_version,
            'reason': run.reason,
            'result': artifact.payload if artifact is not None and run.status == 'SUCCEEDED' else None,
        })
    return {'id': str(batch.id), 'course_id': str(batch.course_id),
            'assignment_id': str(batch.assignment_id) if batch.assignment_id else None,
            'pipeline': PIPELINE, 'status': batch.status, 'mode': batch.mode,
            'threshold': (batch.configuration or {}).get('threshold'),
            'created_at': batch.created_at.isoformat(), 'steps': steps}


def evidence_view(db, batch_id: int, actor: User) -> dict:
    """Teacher-facing projection: stable keys joined to names and line ranges."""
    view = batch_view(db, batch_id, actor)
    batch = db.get(AnalysisBatch, batch_id)
    subjects = (batch.configuration or {}).get('subjects', {})
    items = []
    for step in view['steps']:
        item_id = step['item_id']
        item = db.get(AssignmentItem, int(item_id))
        version = db.get(ProblemVersion, item.problem_version_id) if item else None
        problem = db.get(Problem, version.problem_id) if version else None
        people = (subjects.get(item_id) or {}).get('people', {})

        def describe(answer_key: str) -> dict:
            person = people.get(answer_key) or {}
            return {'submission_id': answer_key.removeprefix('submission-'),
                    'student_id': person.get('student_id'),
                    'student_no': person.get('student_no'),
                    'name': person.get('name'), 'version_no': person.get('version_no')}

        result = step.get('result')
        payload = (result or {}).get('payload') or {}
        pairs = []
        for pair in payload.get('pairs', []):
            pairs.append({
                'left': describe(pair['left_key']), 'right': describe(pair['right_key']),
                'similarity': pair['similarity'], 'jaccard': pair.get('jaccard'),
                'containment_left': pair.get('containment_left'),
                'containment_right': pair.get('containment_right'),
                'shared_fingerprints': pair.get('shared_fingerprints'),
                'matched_tokens': pair.get('matched_tokens'),
                'longest_run_tokens': pair.get('longest_run_tokens'),
                'spans': pair.get('matching_spans', []),
            })
        clusters = [{'members': [describe(key) for key in cluster['member_keys']],
                     'size': cluster['size'], 'max_similarity': cluster['max_similarity']}
                    for cluster in payload.get('clusters', [])]
        insufficient = [{'submission': describe(row['answer_key']), 'reason': row['reason'],
                         'tokens': row.get('tokens')}
                        for row in payload.get('insufficient', [])]
        items.append({
            'item_id': item_id,
            'problem_code': problem.code if problem else None,
            'title': version.title if version else None,
            'status': step['status'], 'business_status': step['business_status'],
            'submission_count': step['submission_count'],
            'implementation_name': step['implementation_name'],
            'implementation_version': step['implementation_version'],
            'method': payload.get('method'), 'parameters': payload.get('parameters'),
            'pairs': pairs, 'clusters': clusters, 'insufficient': insufficient,
        })
    items.sort(key=lambda row: row['item_id'])
    return {'batch_id': view['id'], 'assignment_id': view['assignment_id'],
            'status': view['status'], 'threshold': view['threshold'],
            'items': items,
            'limitations': ['相似度是证据，不是抄袭判定；请结合代码片段与课程要求人工判断',
                            '只比较同一道题内、截止前每人最后一次有效提交']}


def positions_for_review(db, course_id: int, actor: User, assignment_id: int | None) -> dict:
    """How much evidence exists already, so a teacher knows a run is needed."""
    require_teacher(db, course_id, actor.id)
    query = (select(AssignmentItem.id, Assignment.title)
             .join(Assignment, Assignment.id == AssignmentItem.assignment_id)
             .where(Assignment.course_id == course_id))
    if assignment_id is not None:
        query = query.where(Assignment.id == assignment_id)
    rows = db.execute(query).all()
    counts = {item_id: db.scalar(select(Submission.id).where(
        Submission.assignment_item_id == item_id, Submission.status == 'SUBMITTED').limit(1))
        for item_id, _ in rows}
    return {'items': [{'item_id': str(item_id), 'assignment_title': title,
                       'has_submissions': counts[item_id] is not None} for item_id, title in rows]}


def submitted_counts(db, assignment_id: int) -> dict[int, int]:
    rows = db.execute(
        select(Submission.assignment_item_id, Submission.student_id)
        .join(AssignmentItem, AssignmentItem.id == Submission.assignment_item_id)
        .where(AssignmentItem.assignment_id == assignment_id,
               Submission.status == 'SUBMITTED')).all()
    counts: dict[int, int] = {}
    seen: set[tuple[int, int]] = set()
    for item_id, student_id in rows:
        if (item_id, student_id) in seen:
            continue
        seen.add((item_id, student_id))
        counts[item_id] = counts.get(item_id, 0) + 1
    return counts


def run_state(db, batch_id: int) -> dict:
    runs = _runs(db, batch_id)
    return {'total': len(runs),
            'done': sum(1 for run in runs.values() if run.status == 'SUCCEEDED'),
            'failed': sum(1 for run in runs.values() if run.status == 'FAILED'),
            'pending': sum(1 for run in runs.values() if run.status in ('READY', 'RUNNING'))}


def describe_scope(db, course_id: int, actor: User, assignment_id: int | None) -> dict:
    require_teacher(db, course_id, actor.id)
    query = (select(Assignment).where(Assignment.course_id == course_id))
    if assignment_id is not None:
        query = query.where(Assignment.id == assignment_id)
    assignments = []
    for assignment in db.scalars(query.order_by(Assignment.id.desc())):
        rows = db.execute(
            select(AssignmentItem, ProblemVersion, Problem)
            .join(ProblemVersion, ProblemVersion.id == AssignmentItem.problem_version_id)
            .join(Problem, Problem.id == ProblemVersion.problem_id)
            .where(AssignmentItem.assignment_id == assignment.id,
                   Problem.question_type == 'PROGRAMMING')
            .order_by(AssignmentItem.sort_order)).all()
        if not rows:
            continue
        counts = submitted_counts(db, assignment.id)
        assignments.append({
            'id': str(assignment.id), 'title': assignment.title,
            'submission_status': assignment.submission_status,
            'submission_deadline': assignment.submission_deadline.isoformat(),
            'deadline_passed': assignment.submission_deadline <= utcnow(),
            'items': [{'item_id': str(item.id), 'problem_code': problem.code,
                       'title': version.title, 'submitted_students': counts.get(item.id, 0)}
                      for item, version, problem in rows],
        })
    return {'items': assignments}
