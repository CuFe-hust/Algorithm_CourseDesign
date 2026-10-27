"""API-level tests for similarity evidence and complexity reports.

These run against the real PostgreSQL test database through the FastAPI client,
so they cover permissions, idempotency and the JSON the frontend actually reads.
"""
from datetime import timedelta

import pytest

from sqlalchemy import func, select

from app.analysis.framework.contracts import digest
from app.analysis.profiles import seed_profiles
from app.db.base import utcnow
from app.db.models import (AnalysisJob, Assignment, AssignmentItem, Course, JudgeResult,
                           Problem, ProblemComplexityProfile, ProblemVersion, Submission, User)


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


def test_complexity_static_only_when_no_scale_profile(client, auth, db, demo, local_mode):
    item = _programming_item(db, demo)
    version = db.get(ProblemVersion, item.problem_version_id)
    db.query(ProblemComplexityProfile).filter(
        ProblemComplexityProfile.problem_version_id == version.id).delete()
    db.commit()
    submission = _judge(db, _add_submission(db, item, _students(db)[0], ACCEPTED_A))
    from app.analysis import complexity_service
    client.post(f'/api/v1/analysis/submissions/{submission.id}/complexity',
                headers=auth('demo.student01'), json={'request_id': 'cx-static'})
    assert complexity_service.process_one(db, measure=True) is True
    body = client.get(f'/api/v1/analysis/submissions/{submission.id}/complexity',
                      headers=auth('demo.student01')).json()
    assert body['status'] == 'STATIC_ONLY'
    assert body['report']['time']['source'] == 'STATIC'
    assert any('伸缩档案' in text for text in body['report']['limitations'])


def test_complexity_report_has_measurements_curve_and_honest_limits(client, auth, db, demo,
                                                                   local_mode, monkeypatch):
    seed_profiles(db)
    item = _programming_item(db, demo)
    submission = _judge(db, _add_submission(db, item, _students(db)[0], ACCEPTED_A))
    # Keep the ladder short so the test stays fast while still exercising the
    # real subprocess path, the reference reader and the fit.
    from app.analysis import probe
    monkeypatch.setattr(probe, 'MAX_SIZES', (512, 1024, 2048, 4096))
    monkeypatch.setattr(probe, 'TARGET_TOP_MS', 5.0)
    from app.analysis import complexity_service
    assert client.post(f'/api/v1/analysis/submissions/{submission.id}/complexity',
                       headers=auth('demo.student01'), json={'request_id': 'cx-full'}
                       ).status_code == 202
    assert complexity_service.process_one(db, measure=True) is True
    body = client.get(f'/api/v1/analysis/submissions/{submission.id}/complexity',
                      headers=auth('demo.student01')).json()
    assert body['status'] == 'SUCCEEDED'
    report = body['report']
    assert report['time']['class'] in ('O(1)', 'O(log n)', 'O(n)', 'O(n log n)')
    assert report['static']['evidence']
    assert report['dynamic']['rungs'], 'real rungs must be recorded'
    assert all(rung['wall_ms'] >= 0 for rung in report['dynamic']['rungs'])
    assert any(rung.get('reference_ms') for rung in report['dynamic']['rungs']), \
        'the pure input reader must be measured on the same rungs'
    assert report['dynamic'].get('curve'), 'the frontend needs a fitted curve'
    assert report['limitations']
    assert any('不代表最坏情况' in text for text in report['limitations'])


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


def test_complexity_teacher_overview_lists_students(client, auth, db, demo, local_mode):
    item = _programming_item(db, demo)
    students = _students(db)
    for student in students[:2]:
        _judge(db, _add_submission(db, item, student, ACCEPTED_A))
    from app.analysis import complexity_service
    for _ in range(2):
        client.post(f'/api/v1/analysis/submissions/{students[0].id and 0 or 0}/complexity',
                    headers=auth('demo.teacher'), json={'request_id': 'noop'})
        break
    submissions = list(db.scalars(select(Submission).where(
        Submission.student_id.in_([student.id for student in students[:2]]))))
    for submission in submissions:
        client.post(f'/api/v1/analysis/submissions/{submission.id}/complexity',
                    headers=auth('demo.teacher'), json={'request_id': f'overview-{submission.id}'})
        complexity_service.process_one(db, measure=False)
    response = client.get(f'/api/v1/analysis/courses/{demo[0]["course_id"]}/complexity',
                          headers=auth('demo.teacher'))
    assert response.status_code == 200
    items = response.json()['items']
    assert len(items) == 2
    assert {row['student_no'] for row in items} == {student.student_no for student in students[:2]}
    assert all(row['time_class'] for row in items)


def test_complexity_overview_is_teacher_only(client, auth, db, demo):
    assert client.get(f'/api/v1/analysis/courses/{demo[0]["course_id"]}/complexity',
                      headers=auth('demo.student01')).status_code == 403


def test_profile_seed_is_idempotent_and_covers_programming_versions(db, demo):
    first = seed_profiles(db)
    second = seed_profiles(db)
    assert first['created'] >= 0 and second['created'] == 0
    total = db.scalar(select(func.count()).select_from(ProblemComplexityProfile))
    programming = db.scalar(select(func.count()).select_from(ProblemVersion).join(
        Problem, Problem.id == ProblemVersion.problem_id).where(Problem.question_type == 'PROGRAMMING'))
    assert total == programming
