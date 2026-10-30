"""API-level tests for similarity evidence and complexity reports.

These run against the real PostgreSQL test database through the FastAPI client,
so they cover permissions, idempotency and the JSON the frontend actually reads.
"""
import math
from datetime import timedelta

import pytest

from sqlalchemy import func, select

from app.analysis import complexity_service
from app.analysis.framework.contracts import digest
from app.analysis.profiles import seed_profiles
from app.db.base import utcnow
from app.core.errors import AppError
from app.db.models import (AnalysisJob, Assignment, AssignmentItem, Course, JudgeResult,
                           Problem, ProblemComplexityProfile, ProblemVersion, Submission, User, ComplexityReport)


ACCEPTED_A = '''
n = int(input())
a = [tuple(map(int, input().split())) for _ in range(n)]
last, ans = -1, 0
for s, t in sorted(a, key=lambda p: (p[1], p[0])):
    if s >= last:
        last, ans = t, ans + 1
print(ans)
'''

ACCEPTED_B = '''
count = int(input())
items = [tuple(map(int, input().split())) for _ in range(count)]
end_time = -1
total = 0
for start, finish in sorted(items, key=lambda pair: (pair[1], pair[0])):
    if start >= end_time:
        end_time, total = finish, total + 1
print(total)
'''

UNRELATED = '''
data = list(map(int, input().split()))
print(max(data) - min(data))
'''

TINY = 'print(1)\n'


def _students(db, limit=6):
    return list(db.scalars(select(User).where(User.login_name.like('demo.student%'))
                           .order_by(User.id).limit(limit)))


def _programming_item(db, demo=None):
    """First programming item of the seeded demo course, whatever its ids are."""
    if demo is not None:
        for item in demo[0]['items']:
            if item['type'] == 'PROGRAMMING':
                return db.get(AssignmentItem, int(item['id']))
    return db.scalar(
        select(AssignmentItem)
        .select_from(AssignmentItem)
        .join(ProblemVersion, ProblemVersion.id == AssignmentItem.problem_version_id)
        .join(Problem, Problem.id == ProblemVersion.problem_id)
        .where(Problem.question_type == 'PROGRAMMING')
        .order_by(AssignmentItem.id))


def _add_submission(db, item, student, content, *, version=None, when=None, language='python3',
                    client_request_id=None):
    top = db.scalar(select(func.coalesce(func.max(Submission.version_no), 0)).where(
        Submission.assignment_item_id == item.id, Submission.student_id == student.id)) or 0
    submission = Submission(assignment_item_id=item.id, student_id=student.id,
                            version_no=version or (top + 1), content=content, language=language,
                            submitted_at=when or (utcnow() - timedelta(minutes=5)),
                            client_request_id=client_request_id or f'auto-{student.id}-{top + 1}')
    db.add(submission)
    db.flush()
    return submission


def _judge(db, submission, *, verdict='ACCEPTED', is_mock=False, passed=5, total=5,
           execution_mode='LOCAL'):
    job = AnalysisJob(submission_id=submission.id, kind='JUDGE', status='SUCCEEDED',
                      parameters={'execution_mode': execution_mode}, finished_at=utcnow())
    db.add(job)
    db.flush()
    db.add(JudgeResult(job_id=job.id, submission_id=submission.id, verdict=verdict,
                       is_mock=is_mock, algorithm_name='local_judge', algorithm_version='1',
                       cpu_time_ms=None, memory_kib=None, message='summary',
                       passed_cases=passed, executed_cases=total, total_cases=total,
                       execution_mode=execution_mode,
                       runtime_profile='local-dev-v1' if execution_mode == 'LOCAL' else 'mock-v1',
                       measurement_status='UNAVAILABLE_LOCAL'))
    db.commit()
    return submission


# ---------------------------------------------------------------- similarity


def test_similarity_batch_compares_only_the_same_item(client, auth, db, demo):
    item = _programming_item(db, demo)
    assignment_id = demo[0]['items'][0]['assignment_id']
    students = _students(db)
    for student, content in zip(students[:4], (ACCEPTED_A, ACCEPTED_B, UNRELATED, TINY)):
        _add_submission(db, item, student, content)
    db.commit()
    headers = auth('demo.teacher')
    response = client.post(f'/api/v1/analysis/courses/{demo[0]["course_id"]}/code-similarity/batches',
                           headers=headers,
                           json={'request_id': 'sim-http-1', 'assignment_id': assignment_id})
    assert response.status_code == 201, response.text
    batch = response.json()
    assert batch['pipeline'] == 'CODE_SIMILARITY'
    assert [step['item_id'] for step in batch['steps']] == [str(item.id)]

    from app.analysis.framework.runner import process_one
    for _ in range(5):
        if not process_one(db):
            break

    evidence = client.get(f'/api/v1/analysis/batches/{batch["id"]}/similarity', headers=headers)
    assert evidence.status_code == 200, evidence.text
    body = evidence.json()
    first = body['items'][0]
    assert first['status'] == 'SUCCEEDED'
    assert first['submission_count'] == 4
    assert first['pairs'], 'the renamed copy must produce evidence'
    pair = first['pairs'][0]
    assert pair['left']['student_no'] and pair['right']['student_no']
    assert pair['spans'] and pair['spans'][0]['left_start_line'] >= 1
    assert any(row['reason'] == 'INSUFFICIENT_TOKENS' for row in first['insufficient'])
    assert body['limitations']


def test_similarity_batch_is_idempotent_and_rejects_other_courses(client, auth, db, demo):
    item = _programming_item(db, demo)
    assignment_id = demo[0]['items'][0]['assignment_id']
    other_assignment_id = demo[0]['assignments'][1]['id']
    _add_submission(db, item, _students(db)[0], ACCEPTED_A)
    db.commit()
    headers = auth('demo.teacher')
    body = {'request_id': 'sim-http-2', 'assignment_id': assignment_id}
    first = client.post(f'/api/v1/analysis/courses/{demo[0]["course_id"]}/code-similarity/batches',
                        headers=headers, json=body)
    second = client.post(f'/api/v1/analysis/courses/{demo[0]["course_id"]}/code-similarity/batches',
                         headers=headers, json=body)
    assert first.status_code == 201 and second.status_code == 201
    assert first.json()['id'] == second.json()['id']
    conflict = client.post(f'/api/v1/analysis/courses/{demo[0]["course_id"]}/code-similarity/batches',
                           headers=headers,
                           json={'request_id': 'sim-http-2', 'assignment_id': other_assignment_id})
    assert conflict.status_code == 409 and conflict.json()['code'] == 'IDEMPOTENCY_CONFLICT'


def test_similarity_is_teacher_only(client, auth, db, demo):
    response = client.post(f'/api/v1/analysis/courses/{demo[0]["course_id"]}/code-similarity/batches',
                           headers=auth('demo.student01'),
                           json={'request_id': 'sim-student',
                                 'assignment_id': demo[0]['items'][0]['assignment_id']})
    assert response.status_code == 403
    assert client.get('/api/v1/analysis/batches/1/similarity').status_code == 401


def test_similarity_scope_lists_programming_items_with_counts(client, auth, db, demo):
    item = _programming_item(db, demo)
    _add_submission(db, item, _students(db)[0], ACCEPTED_A)
    db.commit()
    response = client.get(f'/api/v1/analysis/courses/{demo[0]["course_id"]}/code-similarity/scope',
                          headers=auth('demo.teacher'),
                          params={'assignment_id': demo[0]['items'][0]['assignment_id']})
    assert response.status_code == 200
    assignments = response.json()['items']
    assert assignments and assignments[0]['items']
    entry = assignments[0]['items'][0]
    assert entry['submitted_students'] == 1
    assert entry['problem_code'] == 'CODE-P01'


# ---------------------------------------------------------------- complexity


@pytest.fixture
def local_mode(monkeypatch):
    monkeypatch.setenv('JUDGE_EXECUTION_MODE', 'LOCAL')


def _ladder(*, sizes=(32, 64, 128, 256, 512, 1024), work=None, baseline=None,
            peak=None, deterministic=True):
    """A synthetic ladder with exactly-shaped counts, used where the test is about
    the service layer rather than the tracer."""
    from app.analysis.trace import schema
    work = work or (lambda n: 2.0 * n * math.log2(n) + 5)
    baseline = baseline or (lambda n: 0.5 * n)
    points = []
    for n in sizes:
        size_work = float(work(n))
        points.append(schema.TracePoint(
            n=n, work=size_work, baseline_work=float(baseline(n)) if callable(baseline) else baseline,
            line_events=int(size_work), jump_events=0,
            max_depth=2,
            peak_bytes=None if peak is None else peak(n),
            lines={'solve:10': int(size_work), 'solve:5': 1},
        ))
    return schema.LadderTrace(language='python3', adapter='python-monitoring-v1',
                              work_unit='LINE+JUMP+库函数折算', points=points,
                              stop_reason='OK', input_family='INT_ARRAY_ROWS',
                              deterministic=deterministic)


@pytest.fixture
def synthetic_trace(monkeypatch):
    from app.analysis.trace import collect as trace_collect
    ladder = _ladder()
    monkeypatch.setattr(trace_collect, 'collect', lambda *args, **kwargs: ladder)
    return ladder


def test_complexity_requires_a_really_accepted_submission(client, auth, db, demo, local_mode):
    item = _programming_item(db, demo)
    student = _students(db)[0]
    failed = _judge(db, _add_submission(db, item, student, ACCEPTED_A, version=1),
                    verdict='WRONG_ANSWER', passed=3, total=5)
    mocked = _judge(db, _add_submission(db, item, student, ACCEPTED_A, version=2),
                    is_mock=True, execution_mode='MOCK')
    ok = _judge(db, _add_submission(db, item, student, ACCEPTED_A, version=3))
    headers = auth('demo.student01')
    body = {'request_id': 'cx-1'}
    assert client.post(f'/api/v1/analysis/submissions/{failed.id}/complexity', headers=headers,
                       json=body).json()['code'] == 'SUBMISSION_NOT_ACCEPTED'
    mocked_response = client.post(f'/api/v1/analysis/submissions/{mocked.id}/complexity',
                                  headers=headers, json=body)
    assert mocked_response.status_code == 409
    assert mocked_response.json()['code'] == 'MOCK_RESULT_NOT_ANALYSABLE'
    accepted = client.post(f'/api/v1/analysis/submissions/{ok.id}/complexity', headers=headers,
                           json=body)
    assert accepted.status_code == 202, accepted.text
    assert accepted.json()['status'] == 'PENDING'


def test_complexity_rejects_a_language_without_a_trace_adapter(client, auth, db, demo, local_mode):
    """Java has a judge toolchain but no exact-count tracer; the request must be
    refused with a stated reason instead of a lexical guess."""
    from app.judge import config as judge_config
    if judge_config.toolchain('java') is None:
        pytest.skip('本机没有 Java 工具链')
    item = _programming_item(db, demo)
    submission = _judge(db, _add_submission(db, item, _students(db)[0], ACCEPTED_A,
                                            language='java'))
    response = client.post(f'/api/v1/analysis/submissions/{submission.id}/complexity',
                           headers=auth('demo.student01'), json={'request_id': 'cx-java'})
    assert response.status_code == 409
    assert response.json()['code'] == 'NO_TRACE_ADAPTER'


def test_complexity_accepts_teacher_requests_but_not_other_students(client, auth, db, demo, local_mode):
    item = _programming_item(db, demo)
    students = _students(db)
    submission = _judge(db, _add_submission(db, item, students[0], ACCEPTED_A))
    assert client.post(f'/api/v1/analysis/submissions/{submission.id}/complexity',
                       headers=auth('demo.student01'), json={'request_id': 'cx-own'}).status_code == 202
    other = client.post(f'/api/v1/analysis/submissions/{submission.id}/complexity',
                        headers=auth('demo.student02'), json={'request_id': 'cx-other'})
    assert other.status_code == 404
    teacher = client.post(f'/api/v1/analysis/submissions/{submission.id}/complexity',
                          headers=auth('demo.teacher'), json={'request_id': 'cx-teacher'})
    assert teacher.status_code == 202


def test_complexity_not_measurable_without_scale_profile(client, auth, db, demo, local_mode):
    item = _programming_item(db, demo)
    version = db.get(ProblemVersion, item.problem_version_id)
    db.query(ProblemComplexityProfile).filter(
        ProblemComplexityProfile.problem_version_id == version.id).delete()
    db.commit()
    submission = _judge(db, _add_submission(db, item, _students(db)[0], ACCEPTED_A))
    client.post(f'/api/v1/analysis/submissions/{submission.id}/complexity',
                headers=auth('demo.student01'), json={'request_id': 'cx-noprofile'})
    assert complexity_service.process_one(db, measure=True) is True
    body = client.get(f'/api/v1/analysis/submissions/{submission.id}/complexity',
                      headers=auth('demo.student01')).json()
    assert body['status'] == 'NOT_MEASURABLE'
    assert body['report']['status'] == 'NOT_MEASURABLE'
    assert body['reason'] and '可伸缩' in body['reason']
    assert body['report']['time'] == {} and body['report']['trace'] == {}


def test_fixed_input_problems_say_the_class_is_not_about_growth(client, auth, db, demo, local_mode):
    seed_profiles(db)
    item = _programming_item(db, demo)
    version = db.get(ProblemVersion, item.problem_version_id)
    profile = db.scalar(select(ProblemComplexityProfile).where(
        ProblemComplexityProfile.problem_version_id == version.id))
    profile.family = 'FIXED'
    profile.spec = {'text': '9 lines of 9 digits'}
    db.commit()
    submission = _judge(db, _add_submission(db, item, _students(db)[0], ACCEPTED_A))
    client.post(f'/api/v1/analysis/submissions/{submission.id}/complexity',
                headers=auth('demo.student01'), json={'request_id': 'cx-fixed'})
    assert complexity_service.process_one(db, measure=True) is True
    body = client.get(f'/api/v1/analysis/submissions/{submission.id}/complexity',
                      headers=auth('demo.student01')).json()
    assert body['status'] == 'NOT_MEASURABLE'
    assert '输入规模固定' in (body['reason'] or '')


def test_trace_report_has_counts_evidence_and_limits(client, auth, db, demo, local_mode,
                                                     synthetic_trace):
    seed_profiles(db)
    item = _programming_item(db, demo)
    submission = _judge(db, _add_submission(db, item, _students(db)[0], ACCEPTED_A))
    client.post(f'/api/v1/analysis/submissions/{submission.id}/complexity',
                headers=auth('demo.student01'), json={'request_id': 'cx-trace'})
    assert complexity_service.process_one(db, measure=True) is True
    body = client.get(f'/api/v1/analysis/submissions/{submission.id}/complexity',
                      headers=auth('demo.student01')).json()
    assert body['status'] == 'SUCCEEDED'
    report = body['report']
    assert report['time']['class'] == 'O(n log n)'
    assert report['time']['source'] == 'TRACE'
    assert report['time']['closed_form']
    assert report['space']['source'] == 'TRACE'
    trace = report['trace']
    assert len(trace['points']) >= 5
    point = trace['points'][0]
    assert point['work'] > 0 and 'baseline_work' in point
    assert trace['evidence'], '逐行证据必须出现在报告里'
    assert trace['adapter'] == 'python-monitoring-v1'
    assert report['trace_meta']['work_unit']
    assert any('不代表最坏情况' in text for text in report['limitations'])
    assert any('输入解析基准' in text for text in report['limitations'])


def test_trace_report_records_a_recurrence_when_the_call_tree_has_one(client, auth, db, demo,
                                                                      local_mode, monkeypatch):
    from app.analysis.trace import collect as trace_collect
    from app.analysis.trace import schema
    points = []
    sizes = (32, 64, 128, 256, 512)
    for n in sizes:
        work = 2.0 * n * math.log2(n)
        function = schema.FunctionTrace(name='merge_sort')
        for size in (n, n // 2, n // 4):
            if size > 4:
                function.add_sample(schema.FrameSample(
                    args=(size,), cost=0.5 * size,
                    children=((size // 2,), (size // 2,))))
        points.append(schema.TracePoint(n=n, work=work, line_events=int(work),
                                        functions={'merge_sort': function}))
    ladder = schema.LadderTrace(language='python3', adapter='python-monitoring-v1',
                                work_unit='LINE+JUMP+库函数折算', points=points,
                                input_family='INT_ARRAY')
    monkeypatch.setattr(trace_collect, 'collect', lambda *a, **k: ladder)
    seed_profiles(db)
    item = _programming_item(db, demo)
    submission = _judge(db, _add_submission(db, item, _students(db)[0], ACCEPTED_A))
    client.post(f'/api/v1/analysis/submissions/{submission.id}/complexity',
                headers=auth('demo.student01'), json={'request_id': 'cx-rec'})
    assert complexity_service.process_one(db, measure=True) is True
    report = client.get(f'/api/v1/analysis/submissions/{submission.id}/complexity',
                        headers=auth('demo.student01')).json()['report']
    assert report['time']['method'] == 'RECURRENCE'
    assert report['time']['recurrence'] == 'T(n) = 2·T(n/2) + O(n)'
    assert any(row['kind'] == 'RECURSION' for row in report['trace']['evidence'])


def test_real_tracing_runs_the_submission(client, auth, db, demo, local_mode):
    """One end-to-end measurement with the real Python tracer: no monkeypatch."""
    seed_profiles(db)
    item = _programming_item(db, demo)
    version = db.get(ProblemVersion, item.problem_version_id)
    profile = db.scalar(select(ProblemComplexityProfile).where(
        ProblemComplexityProfile.problem_version_id == version.id))
    # Keep the ladder short so the suite stays fast while still exercising the
    # real subprocess path and the count collection.
    profile.spec = {'max_n': 256}
    db.commit()
    submission = _judge(db, _add_submission(db, item, _students(db)[0], ACCEPTED_A))
    client.post(f'/api/v1/analysis/submissions/{submission.id}/complexity',
                headers=auth('demo.student01'), json={'request_id': 'cx-real'})
    assert complexity_service.process_one(db, measure=True) is True
    body = client.get(f'/api/v1/analysis/submissions/{submission.id}/complexity',
                      headers=auth('demo.student01')).json()
    assert body['status'] == 'SUCCEEDED', body
    report = body['report']
    assert report['time']['class'] in ('O(1)', 'O(log n)', 'O(n)', 'O(n log n)', 'O(n^2)')
    assert report['trace']['points'], 'real rungs must be recorded'
    assert report['trace']['deterministic'] is True


def test_complexity_request_is_idempotent(client, auth, db, demo, local_mode):
    item = _programming_item(db, demo)
    submission = _judge(db, _add_submission(db, item, _students(db)[0], ACCEPTED_A))
    headers = auth('demo.student01')
    first = client.post(f'/api/v1/analysis/submissions/{submission.id}/complexity',
                        headers=headers, json={'request_id': 'cx-idem'})
    second = client.post(f'/api/v1/analysis/submissions/{submission.id}/complexity',
                         headers=headers, json={'request_id': 'cx-idem-other'})
    assert first.status_code == second.status_code == 202
    from app.db.models import ComplexityReport
    count = db.scalar(select(func.count()).select_from(ComplexityReport).where(
        ComplexityReport.submission_id == submission.id))
    assert count == 1, 'one report per submission, regardless of request keys'


def test_complexity_teacher_overview_lists_students(client, auth, db, demo, local_mode,
                                                    synthetic_trace):
    seed_profiles(db)
    item = _programming_item(db, demo)
    students = _students(db)
    for student in students[:2]:
        _judge(db, _add_submission(db, item, student, ACCEPTED_A))
    for student in students[:2]:
        submission = db.scalar(select(Submission).where(
            Submission.student_id == student.id,
            Submission.assignment_item_id == item.id))
        client.post(f'/api/v1/analysis/submissions/{submission.id}/complexity',
                    headers=auth('demo.teacher'),
                    json={'request_id': f'overview-{submission.id}'})
        assert complexity_service.process_one(db, measure=True) is True
    response = client.get(f'/api/v1/analysis/courses/{demo[0]["course_id"]}/complexity',
                          headers=auth('demo.teacher'))
    assert response.status_code == 200
    items = response.json()['items']
    assert len(items) == 2
    assert {row['student_no'] for row in items} == {student.student_no for student in students[:2]}
    assert all(row['time_class'] == 'O(n log n)' for row in items)
    assert all(row['time_source'] == 'TRACE' for row in items)


def test_teacher_batch_queues_every_accepted_submission(client, auth, db, demo, local_mode):
    """The 60-student class is the main use case; one request queues the item."""
    item = _programming_item(db, demo)
    students = _students(db)
    for student in students[:3]:
        _judge(db, _add_submission(db, item, student, ACCEPTED_A))
    _judge(db, _add_submission(db, item, students[3], UNRELATED), verdict='WRONG_ANSWER')
    headers = auth('demo.teacher')
    response = client.post(f'/api/v1/analysis/courses/{demo[0]["course_id"]}/complexity/batch',
                           headers=headers,
                           json={'request_id': f'batch-{item.id}',
                                 'assignment_item_id': str(item.id)})
    assert response.status_code == 202, response.text
    body = response.json()
    assert body['queued'] == 3
    assert body['ineligible'] >= 1
    assert body['ineligible_reasons'].get('SUBMISSION_NOT_ACCEPTED') == 1
    again = client.post(f'/api/v1/analysis/courses/{demo[0]["course_id"]}/complexity/batch',
                        headers=headers,
                        json={'request_id': f'batch-again-{item.id}',
                              'assignment_item_id': str(item.id)})
    assert again.json()['queued'] == 0
    assert again.json()['skipped'] == 3


def test_concurrent_batch_requests_do_not_duplicate_reports(client, auth, db, demo, local_mode):
    from app.db.models import ComplexityReport
    item = _programming_item(db, demo)
    _judge(db, _add_submission(db, item, _students(db)[0], ACCEPTED_A))
    headers = auth('demo.teacher')
    body = {'request_id': 'batch-race', 'assignment_item_id': str(item.id)}
    first = client.post(f'/api/v1/analysis/courses/{demo[0]["course_id"]}/complexity/batch',
                        headers=headers, json=body)
    second = client.post(f'/api/v1/analysis/courses/{demo[0]["course_id"]}/complexity/batch',
                         headers=headers, json=body)
    assert first.status_code == 202 and second.status_code == 202
    count = db.scalar(select(func.count()).select_from(ComplexityReport).where(
        ComplexityReport.assignment_item_id == item.id))
    assert count == 1


def test_history_keeps_the_superseded_conclusion(db, demo, local_mode, monkeypatch):
    """An implementation upgrade resets the row; the old verdict must not vanish."""
    from app.analysis.trace import collect as trace_collect
    from app.db.models import ComplexityReport
    ladder = _ladder()
    monkeypatch.setattr(trace_collect, 'collect', lambda *a, **k: ladder)
    seed_profiles(db)
    item = _programming_item(db, demo)
    submission = _judge(db, _add_submission(db, item, _students(db)[0], ACCEPTED_A))
    student = db.get(User, submission.student_id)
    complexity_service.request_report(db, submission.id, student, 'hist-1')
    complexity_service.process_one(db, measure=True)
    report = db.scalar(select(ComplexityReport).where(
        ComplexityReport.submission_id == submission.id))
    db.refresh(report)
    old_class = report.time_class
    assert old_class == 'O(n log n)'
    report.implementation_version = '0'
    db.commit()
    complexity_service.request_report(db, submission.id, student, 'hist-2')
    db.refresh(report)
    assert report.history, '旧结论必须归档'
    assert report.history[-1]['time_class'] == old_class
    assert report.status == 'PENDING'


def test_teacher_batch_is_teacher_only(client, auth, db, demo, local_mode):
    item = _programming_item(db, demo)
    response = client.post(f'/api/v1/analysis/courses/{demo[0]["course_id"]}/complexity/batch',
                           headers=auth('demo.student01'),
                           json={'request_id': f'batch-{item.id}',
                                 'assignment_item_id': str(item.id)})
    assert response.status_code == 403


def test_complexity_overview_is_teacher_only(client, auth, db, demo):
    assert client.get(f'/api/v1/analysis/courses/{demo[0]["course_id"]}/complexity',
                      headers=auth('demo.student01')).status_code == 403


def test_report_constraints_reject_a_class_the_fitter_cannot_produce(db, demo):
    """The CHECK constraints must reject bad rows, not merely document the rule."""
    from sqlalchemy.exc import IntegrityError
    from app.db.models import ComplexityReport

    item = _programming_item(db, demo)
    submission = _judge(db, _add_submission(db, item, _students(db)[0], ACCEPTED_A))

    def make(**overrides):
        values = dict(submission_id=submission.id, assignment_item_id=item.id,
                      student_id=submission.student_id, status='SUCCEEDED',
                      language='python3', summary={}, limitations=[],
                      implementation_name='t', implementation_version='1',
                      requested_by=submission.student_id, requested_at=utcnow(),
                      attempt_no=0, history=[], time_class='O(n log n)', space_class='O(1)',
                      trace_meta={}, trace_series={})
        values.update(overrides)
        return ComplexityReport(**values)

    for report in (
        make(time_class='O(log^2 n)'),
        make(time_class=None, space_class=None),
        make(status='PENDING', time_class='O(n)', space_class='O(1)'),
        make(status='NOT_MEASURABLE', time_class='O(n)', space_class='O(1)'),
    ):
        db.add(report)
        try:
            db.commit()
            raise AssertionError('非法报告被接受，约束没有生效')
        except IntegrityError:
            db.rollback()
    db.add(make(time_class='O(n!)'))
    db.commit()


def test_profile_seed_is_idempotent_and_covers_programming_versions(db, demo):
    first = seed_profiles(db)
    second = seed_profiles(db)
    assert first['created'] >= 0 and second['created'] == 0
    total = db.scalar(select(func.count()).select_from(ProblemComplexityProfile))
    programming = db.scalar(select(func.count()).select_from(ProblemVersion).join(
        Problem, Problem.id == ProblemVersion.problem_id).where(Problem.question_type == 'PROGRAMMING'))
    assert total == programming

def test_every_input_family_is_accepted_by_the_profile_constraint(db, demo):
    """The CHECK in pg0009 must accept every family the generator can emit.

    The family list exists in three places (generator, model, migration); this
    test walks the generator's list through the database so the three cannot
    drift silently.
    """
    from app.analysis import probe
    from app.db.models import ProblemComplexityProfile, ProblemVersion
    version = db.scalar(select(ProblemVersion).join(
        Problem, Problem.id == ProblemVersion.problem_id)
        .where(Problem.question_type == 'PROGRAMMING').order_by(ProblemVersion.id))
    assert version is not None
    for family in probe.FAMILIES:
        profile = ProblemComplexityProfile(problem_version_id=version.id, family=family,
                                           spec={}, source='SEEDED', version_no=1)
        db.add(profile)
        db.commit()  # must not raise IntegrityError for a family the generator emits
        db.delete(profile)
        db.commit()


def test_complexity_wrong_worker_context_does_not_poison_pending_report(db,demo,local_mode,monkeypatch):
    item=_programming_item(db,demo);submission=_judge(db,_add_submission(db,item,_students(db)[0],ACCEPTED_A));actor=db.get(User,submission.student_id)
    complexity_service.request_report(db,submission.id,actor,'context-1')
    monkeypatch.setenv('JUDGE_EXECUTION_MODE','MOCK')
    assert complexity_service.claim(db) is None
    report=db.scalar(select(ComplexityReport).where(ComplexityReport.submission_id==submission.id));assert report.status=='PENDING' and report.attempt_no==0
    monkeypatch.setenv('JUDGE_EXECUTION_MODE','LOCAL');assert complexity_service.claim(db).id==report.id


def test_complexity_explicit_retry_is_idempotent_bounded_and_fences_old_attempt(db,demo,local_mode):
    item=_programming_item(db,demo);submission=_judge(db,_add_submission(db,item,_students(db)[0],ACCEPTED_A));actor=db.get(User,submission.student_id)
    complexity_service.request_report(db,submission.id,actor,'retry-original')
    report=complexity_service.claim(db);old_ticket=db.info['complexity_claim'];report.lease_expires_at=utcnow()-timedelta(seconds=1);db.commit()
    assert complexity_service.recover_expired(db)==1
    complexity_service.request_report(db,submission.id,actor,'retry-original');db.refresh(report);assert report.status=='FAILED'
    complexity_service.request_report(db,submission.id,actor,'retry-new');db.refresh(report);assert report.status=='PENDING' and report.history[-1]['event']=='EXPLICIT_RETRY'
    complexity_service.claim(db);new_ticket=db.info['complexity_claim'];assert new_ticket[1]==2
    db.info['complexity_claim']=old_ticket;complexity_service._write(db,report.id,status='SUCCEEDED',time_class='O(1)');db.refresh(report)
    assert report.status=='RUNNING' and report.time_class is None
    db.info['complexity_claim']=new_ticket;complexity_service._write(db,report.id,status='FAILED',error_message='synthetic infrastructure failure');db.refresh(report)
    complexity_service.request_report(db,submission.id,actor,'retry-new');db.refresh(report);assert report.status=='FAILED'
    report.attempt_no=3;db.commit()
    with pytest.raises(AppError) as err:complexity_service.request_report(db,submission.id,actor,'retry-over-limit')
    assert err.value.code=='COMPLEXITY_RETRY_LIMIT'
