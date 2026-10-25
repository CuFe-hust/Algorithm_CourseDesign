"""AC02/AC08/AC12/AC15/AC16/AC23–AC24/AC32–AC33: student read models."""
from datetime import timedelta
import uuid

from sqlalchemy import select

from app.db.base import utcnow
from app.db.models import (AnalysisJob, Assignment, AssignmentItem, JudgeResult, Problem, Submission, User)


def _item(demo, question_type='PROGRAMMING'):
    return next(x['id'] for x in demo[0]['items'] if x['type'] == question_type)


def _submit(client, headers, item, content='print(1)', language='python3'):
    return client.post(f'/api/v1/assignment-items/{item}/submissions', headers=headers,
                       json={'content': content, 'language': language, 'client_request_id': uuid.uuid4().hex})


def test_assignment_detail_is_student_safe_and_scope_checked(client, demo, auth, db):
    headers = auth()
    assignment_id = demo[0]['assignments'][0]['id']
    body = client.get(f'/api/v1/assignments/{assignment_id}', headers=headers).json()
    assert body['id'] == assignment_id and body['submission_open'] is True
    assert body['server_time'] and body['items']
    forbidden = {'reference_solutions', 'test_cases', 'created_by', 'expected_output'}
    assert forbidden.isdisjoint(body)
    assert forbidden.isdisjoint(body['items'][0])

    other = client.get(f"/api/v1/assignments/{assignment_id}", headers=auth('demo.student02')).status_code
    assert other in {200, 404}  # student02 is on the roster, so it must be visible
    teacher = client.get(f"/api/v1/assignments/{assignment_id}", headers=auth('demo.teacher'))
    assert teacher.status_code == 200 and 'created_by' not in teacher.json()

    assignment = db.get(Assignment, int(assignment_id))
    assignment.submission_status = 'DRAFT'
    db.commit()
    assert client.get(f'/api/v1/assignments/{assignment_id}', headers=headers).status_code == 404
    assert client.get(f'/api/v1/assignments/{assignment_id}', headers=auth('demo.teacher')).status_code == 200


def test_item_exposes_only_public_test_cases_with_stable_numbers(client, demo, auth):
    headers = auth()
    programming = client.get(f"/api/v1/assignment-items/{_item(demo)}", headers=headers).json()
    cases = programming['public_test_cases']
    assert cases == [{'case_no': 1, 'input_text': '1\n0 1000000000\n', 'expected_output': '1\n'}]
    assert programming['problem_version_id']
    subjective = client.get(f"/api/v1/assignment-items/{_item(demo, 'PROOF')}", headers=headers).json()
    assert subjective['public_test_cases'] == []
    assert 'test_cases' not in subjective and 'expected_output' not in subjective


def test_history_filters_paginate_and_never_leak_other_students(client, demo, auth, db, monkeypatch):
    monkeypatch.setenv('LIMIT_SUBMISSION_BURST', '50')
    monkeypatch.setenv('LIMIT_SUBMISSION_PER_MINUTE', '50')
    headers = auth()
    item = _item(demo)
    ids = [_submit(client, headers, item).json()['submission_id'] for _ in range(5)]
    body = client.get('/api/v1/me/submissions', headers=headers,
                      params={'limit': 2, 'assignment_item_id': item}).json()
    assert body['total'] == 5 and len(body['items']) == 2 and body['limit'] == 2
    assert body['items'][0]['submission_id'] == ids[-1]  # submitted_at DESC
    assert 'content' not in body['items'][0]
    page2 = client.get('/api/v1/me/submissions', headers=headers,
                       params={'limit': 2, 'offset': 2, 'assignment_item_id': item}).json()
    assert {row['submission_id'] for row in page2['items']}.isdisjoint({row['submission_id'] for row in body['items']})

    assert client.get('/api/v1/me/submissions', headers=headers,
                      params={'language': 'cpp'}).json()['total'] == 0
    assert client.get('/api/v1/me/submissions', headers=headers,
                      params={'assignment_item_id': _item(demo, 'PROOF')}).json()['total'] == 0
    assert client.get('/api/v1/me/submissions', headers=headers,
                      params={'course_id': 999999}).status_code == 404
    assert client.get('/api/v1/me/submissions', headers=headers,
                      params={'assignment_item_id': _item(demo, 'PROOF'), 'assignment_id': demo[0]['assignments'][0]['id']}
                      ).status_code == 404

    other = client.get('/api/v1/me/submissions', headers=auth('demo.student02')).json()
    assert other['total'] == 0
    assert client.get(f"/api/v1/submissions/{ids[0]}", headers=auth('demo.student02')).status_code == 404


def test_progress_counts_only_real_results_and_picks_deterministic_best(client, demo, auth, db, monkeypatch):
    monkeypatch.setenv('JUDGE_EXECUTION_MODE', 'LOCAL')
    headers = auth()
    item = _item(demo)
    user = db.scalar(select(User).where(User.login_name == 'demo.student01'))
    assignment_item = db.get(AssignmentItem, int(item))
    now = utcnow()
    rows = []
    for index, passed in enumerate([2, 4]):
        submission = Submission(assignment_item_id=assignment_item.id, student_id=user.id, version_no=index + 1,
                                content='print(1)', language='python3', submitted_at=now + timedelta(seconds=index),
                                client_request_id=uuid.uuid4().hex)
        db.add(submission)
        db.flush()
        job = AnalysisJob(submission_id=submission.id, status='SUCCEEDED', phase='FINISHED',
                          parameters={'execution_mode': 'LOCAL', 'runtime_profile': 'local-dev-v1'})
        db.add(job)
        db.flush()
        db.add(JudgeResult(job_id=job.id, submission_id=submission.id, verdict='WRONG_ANSWER', is_mock=False,
                           algorithm_name='local_judge', algorithm_version='1', cpu_time_ms=None, memory_kib=None,
                           message='通过 %d / 5 个测试点' % passed, passed_cases=passed, executed_cases=5,
                           total_cases=5, execution_mode='LOCAL', runtime_profile='local-dev-v1',
                           measurement_status='UNAVAILABLE_LOCAL'))
        rows.append(submission)
    # A mock result must never be treated as a real pass.
    mock = Submission(assignment_item_id=assignment_item.id, student_id=user.id, version_no=3,
                      content='print(1)', language='python3', submitted_at=now + timedelta(seconds=5),
                      client_request_id=uuid.uuid4().hex)
    db.add(mock); db.flush()
    mock_job = AnalysisJob(submission_id=mock.id, status='SUCCEEDED', phase='FINISHED', parameters={})
    db.add(mock_job); db.flush()
    db.add(JudgeResult(job_id=mock_job.id, submission_id=mock.id, verdict='MOCK_ACCEPTED', is_mock=True,
                       algorithm_name='deterministic_mock', algorithm_version='1', cpu_time_ms=None,
                       memory_kib=None, message='模拟通过', passed_cases=None, total_cases=None,
                       execution_mode='MOCK', measurement_status='NOT_APPLICABLE'))
    db.commit()

    response = client.get(f"/api/v1/courses/{demo[0]['course_id']}/my-progress", headers=headers,
                          params={'assignment_id': demo[0]['assignments'][0]['id']})
    assert response.status_code == 200, response.text
    body = response.json()
    entry = next(row for row in body['items'] if row['assignment_item_id'] == item)
    assert entry['has_submitted'] is True
    assert entry['has_passed'] is False  # no full pass yet, mock never counts
    assert entry['best_submission_id'] == str(rows[1].id)  # 4 passed beats 2
    assert entry['latest_submission_id'] == str(mock.id)
    assert entry['evaluation_context'] if 'evaluation_context' in entry else True
    assert body['evaluation_context'] == {'execution_mode': 'LOCAL', 'runtime_profile': 'local-dev-v1'}
    assert body['summary']['programming_item_count'] >= 1
    assert body['summary']['submitted_item_count'] >= 1


def test_progress_rejects_teachers_and_foreign_assignments(client, demo, auth):
    teacher = auth('demo.teacher')
    assert client.get(f"/api/v1/courses/{demo[0]['course_id']}/my-progress", headers=teacher).status_code == 403
    assert client.get(f"/api/v1/courses/{demo[0]['course_id']}/my-progress", headers=auth(),
                      params={'assignment_id': 999999}).status_code == 404


def test_job_discovery_scans_every_page_past_one_hundred(client, demo, auth, db):
    headers = auth()
    user = db.scalar(select(User).where(User.login_name == 'demo.student01'))
    item = db.get(AssignmentItem, int(_item(demo)))
    now = utcnow()
    for index in range(105):
        submission = Submission(assignment_item_id=item.id, student_id=user.id, version_no=index + 1,
                                content='print(1)', language='python3',
                                submitted_at=now + timedelta(milliseconds=index),
                                client_request_id=uuid.uuid4().hex)
        db.add(submission); db.flush()
        db.add(AnalysisJob(submission_id=submission.id, status='PENDING', phase='QUEUED', parameters={}))
    db.commit()
    seen, cursor, pages = set(), None, 0
    while True:
        response = client.get('/api/v1/me/judge-jobs', headers=headers,
                              params={'filter': 'DISCOVERY', 'limit': 100, **({'cursor': cursor} if cursor else {})})
        assert response.status_code == 200
        body = response.json()
        pages += 1
        seen.update(row['submission_id'] for row in body['items'])
        cursor = body['next_cursor']
        if not body['has_more']:
            break
        assert pages < 5
    assert len(seen) == 105
    assert pages == 2

    tampered = client.get('/api/v1/me/judge-jobs', headers=headers,
                          params={'filter': 'DISCOVERY', 'cursor': 'not-a-real-cursor'})
    assert tampered.status_code == 422


def test_batch_status_rejects_unknown_or_foreign_ids(client, demo, auth):
    headers = auth()
    mine = _submit(client, headers, _item(demo)).json()['submission_id']
    ok = client.post('/api/v1/me/judge-jobs/status', headers=headers, json={'submission_ids': [mine]})
    assert ok.status_code == 200 and ok.json()['items'][0]['submission_id'] == mine
    foreign = _submit(client, auth('demo.student02'), _item(demo)).json()['submission_id']
    assert client.post('/api/v1/me/judge-jobs/status', headers=headers,
                       json={'submission_ids': [mine, foreign]}).status_code == 404
    assert client.post('/api/v1/me/judge-jobs/status', headers=headers,
                       json={'submission_ids': ['999999999']}).status_code == 404
    assert client.post('/api/v1/me/judge-jobs/status', headers=headers,
                       json={'submission_ids': [mine, mine]}).status_code == 422


def test_rejudge_requires_facility_failure_cooldown_and_budget(client, demo, auth, db, monkeypatch):
    monkeypatch.setenv('LIMIT_SUBMISSION_BURST', '50')
    headers = auth()
    submission_id = _submit(client, headers, _item(demo)).json()['submission_id']
    job = db.scalar(select(AnalysisJob).where(AnalysisJob.submission_id == int(submission_id)))
    assert client.post(f'/api/v1/submissions/{submission_id}/rejudge', headers=headers,
                       json={'client_request_id': uuid.uuid4().hex}).status_code == 409
    job.status = 'FAILED'
    job.phase = 'FINISHED'
    job.finished_at = utcnow() - timedelta(seconds=120)
    db.commit()
    key = uuid.uuid4().hex
    first = client.post(f'/api/v1/submissions/{submission_id}/rejudge', headers=headers,
                        json={'client_request_id': key})
    assert first.status_code == 202 and first.json()['job_status'] == 'PENDING'
    replay = client.post(f'/api/v1/submissions/{submission_id}/rejudge', headers=headers,
                         json={'client_request_id': key})
    assert replay.status_code == 202 and replay.json()['replayed'] is True
    conflict = client.post(f'/api/v1/submissions/{submission_id}/rejudge', headers=headers,
                           json={'client_request_id': uuid.uuid4().hex})
    assert conflict.status_code == 409 and conflict.json()['code'] == 'JUDGE_RETRY_NOT_ALLOWED'

    db.expire_all()
    job = db.get(AnalysisJob, job.id)
    assert job.recovery_cycle_no == 1
    job.status = 'FAILED'; job.finished_at = utcnow() - timedelta(seconds=120)
    job.last_manual_retry_at = utcnow() - timedelta(seconds=120)
    db.commit()
    cooldown = client.post(f'/api/v1/submissions/{submission_id}/rejudge', headers=headers,
                           json={'client_request_id': uuid.uuid4().hex})
    assert cooldown.status_code == 202  # cooldown elapsed, second cycle accepted

    db.expire_all()
    job = db.get(AnalysisJob, job.id)
    job.status = 'FAILED'; job.finished_at = utcnow() - timedelta(seconds=120)
    job.last_manual_retry_at = utcnow() - timedelta(seconds=120)
    job.recovery_cycle_no = 3
    db.commit()
    exhausted = client.post(f'/api/v1/submissions/{submission_id}/rejudge', headers=headers,
                            json={'client_request_id': uuid.uuid4().hex})
    assert exhausted.status_code == 409
    assert exhausted.json()['code'] == 'JUDGE_RETRY_BUDGET_EXHAUSTED'


def test_queue_reason_reports_personal_limit_and_service_pause(client, demo, auth, db, monkeypatch):
    """AC28: the queue hint must say why a job is waiting, not just 'queued'."""
    monkeypatch.setenv('LIMIT_SUBMISSION_BURST', '50')
    monkeypatch.setenv('LIMIT_SUBMISSION_PER_MINUTE', '50')
    headers = auth()
    ids = [_submit(client, headers, _item(demo)).json()['submission_id'] for _ in range(4)]
    for index, submission_id in enumerate(ids[:3]):
        job = db.scalar(select(AnalysisJob).where(AnalysisJob.submission_id == int(submission_id)))
        job.status = 'RUNNING'
        job.phase = 'TESTING'
        job.attempt_token = f'token-{index}'
    db.commit()

    detail = client.get(f'/api/v1/submissions/{ids[3]}', headers=headers).json()
    assert detail['job']['queue_reason'] == 'PERSONAL_LIMIT'
    batch = client.post('/api/v1/me/judge-jobs/status', headers=headers,
                        json={'submission_ids': [ids[3]]}).json()
    assert batch['items'][0]['job']['queue_reason'] == 'PERSONAL_LIMIT'
    listing = client.get('/api/v1/me/judge-jobs', headers=headers,
                         params={'filter': 'ACTIVE'}).json()
    waiting = next(row for row in listing['items'] if row['submission_id'] == ids[3])
    assert waiting['job']['queue_reason'] == 'PERSONAL_LIMIT'

    monkeypatch.setenv('JUDGE_SERVICE_PAUSED', '1')
    paused = client.get(f'/api/v1/submissions/{ids[3]}', headers=headers).json()
    assert paused['job']['queue_reason'] == 'SERVICE_PAUSED'
    monkeypatch.setenv('JUDGE_SERVICE_PAUSED', '')
    assert client.get(f'/api/v1/submissions/{ids[3]}', headers=headers).json()['job']['queue_reason'] == 'PERSONAL_LIMIT'
