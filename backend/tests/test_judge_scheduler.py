"""AC17–AC21, AC26, AC29–AC30 and RV01: LOCAL scheduling, ownership and recovery."""
import os
import threading
import time
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.db.base import utcnow
from app.db.models import AnalysisJob, JudgeAttempt, JudgeResult, Submission, User
from app.judge import config, local, recovery, results
from app.judge.scheduler import Scheduler
from app.judge.supervisor import SUPERVISOR, Marker, marker_path

CORRECT = '''import sys
data = sys.stdin.read().split()
n = int(data[0])
pairs = []
for i in range(n):
    start = int(data[1 + 2 * i]); end = int(data[2 + 2 * i])
    pairs.append((end, start))
pairs.sort()
last = -1
count = 0
for end, start in pairs:
    if start >= last:
        count += 1
        last = end
print(count)
'''


@pytest.fixture
def local_mode(monkeypatch, judge_work_root):
    monkeypatch.setenv('JUDGE_EXECUTION_MODE', 'LOCAL')
    monkeypatch.setenv('LIMIT_SUBMISSION_BURST', '50')
    monkeypatch.setenv('LIMIT_SUBMISSION_PER_MINUTE', '50')
    monkeypatch.setenv('LIMIT_PERSONAL_BACKLOG', '100')
    monkeypatch.setenv('LIMIT_NODE_BACKLOG', '500')
    return 'LOCAL'


def _item(demo):
    return next(x['id'] for x in demo[0]['items'] if x['type'] == 'PROGRAMMING')


def _submit(client, headers, demo, content=CORRECT):
    response = client.post(f'/api/v1/assignment-items/{_item(demo)}/submissions', headers=headers,
                           json={'content': content, 'language': 'python3',
                                 'client_request_id': uuid.uuid4().hex})
    assert response.status_code == 202, response.text
    return response.json()['submission_id']


def test_local_job_produces_real_summary_and_progress(client, demo, auth, db, local_mode):
    headers = auth()
    submission_id = _submit(client, headers, demo)
    job = db.scalar(select(AnalysisJob).where(AnalysisJob.submission_id == int(submission_id)))
    assert job.parameters['execution_mode'] == 'LOCAL'
    assert job.parameters['runtime_profile'] == config.LOCAL_PROFILE

    scheduler = Scheduler(db.bind, mode='LOCAL', concurrency=1)
    assert scheduler.run_once() == 1

    detail = client.get(f'/api/v1/submissions/{submission_id}', headers=headers).json()
    assert detail['job_status'] == 'SUCCEEDED'
    result = detail['result']
    assert result['verdict'] == 'ACCEPTED' and result['is_mock'] is False
    assert result['passed_cases'] == 5 and result['total_cases'] == 5
    assert result['cpu_time_ms'] is None and result['memory_kib'] is None
    assert result['execution_mode'] == 'LOCAL'
    assert result['measurement_status'] == 'UNAVAILABLE_LOCAL'
    assert 'MOCK' not in detail['job_status']
    assert detail['job']['phase'] == 'FINISHED' and detail['job']['attempt_no'] == 1

    progress = client.get(f"/api/v1/courses/{demo[0]['course_id']}/my-progress", headers=headers).json()
    entry = next(row for row in progress['items'] if row['assignment_item_id'] == _item(demo))
    assert entry['has_passed'] is True
    assert entry['best_submission_id'] == submission_id
    assert entry['has_unresolved_jobs'] is False


def test_personal_concurrency_caps_at_three(client, demo, auth, db, local_mode, monkeypatch):
    monkeypatch.setenv('JUDGE_PER_STUDENT_CONCURRENCY', '3')
    headers = auth()
    ids = [_submit(client, headers, demo) for _ in range(5)]
    scheduler = Scheduler(db.bind, mode='LOCAL', concurrency=5)
    assert scheduler.run_once() == 3
    statuses = dict(db.execute(select(AnalysisJob.submission_id, AnalysisJob.status)).all())
    assert sorted(statuses[int(value)] for value in ids) == ['PENDING', 'PENDING', 'SUCCEEDED', 'SUCCEEDED', 'SUCCEEDED']
    assert scheduler.run_once() == 2
    db.expire_all()
    assert {row.status for row in db.scalars(select(AnalysisJob))} == {'SUCCEEDED'}


def test_mode_isolation_keeps_mock_and_local_apart(client, demo, auth, db, local_mode, monkeypatch):
    headers = auth()
    mock_submission = _submit(client, headers, demo)
    local_submission = _submit(client, headers, demo)
    job = db.scalar(select(AnalysisJob).where(AnalysisJob.submission_id == int(mock_submission)))
    job.parameters = {'test_suite_id': job.parameters['test_suite_id']}
    db.commit()
    from app.analysis.worker import process_pending_jobs
    assert process_pending_jobs(db, 10) == 1
    db.expire_all()
    assert db.get(AnalysisJob, job.id).status == 'SUCCEEDED'
    local_job = db.scalar(select(AnalysisJob).where(AnalysisJob.submission_id == int(local_submission)))
    assert local_job.status == 'PENDING'
    assert Scheduler(db.bind, mode='LOCAL', concurrency=1).run_once() == 1
    db.expire_all()
    assert db.get(AnalysisJob, local_job.id).status == 'SUCCEEDED'


def test_ownership_loss_discards_result(client, demo, auth, db, local_mode):
    headers = auth()
    submission_id = _submit(client, headers, demo)
    job = db.scalar(select(AnalysisJob).where(AnalysisJob.submission_id == int(submission_id)))
    db.execute(AnalysisJob.__table__.update().where(AnalysisJob.id == job.id)
               .values(status='RUNNING', attempt_token='other-token', phase='TESTING',
                       lease_expires_at=utcnow() + timedelta(seconds=60)))
    db.commit()
    from app.judge.local import CaseInput
    saved = results.record_success(db, job.id, 'stale-token',
                                   local.ExecutionOutcome('ACCEPTED', 5, 5, 5, 10), 'LOCAL', 'local-dev-v1')
    assert saved is None
    db.expire_all()
    assert db.scalar(select(JudgeResult).where(JudgeResult.submission_id == int(submission_id))) is None


def test_recovery_kills_the_old_execution_before_requeueing(client, demo, auth, db, local_mode, judge_work_root):
    headers = auth()
    submission_id = _submit(client, headers, demo)
    job = db.scalar(select(AnalysisJob).where(AnalysisJob.submission_id == int(submission_id)))
    db.execute(AnalysisJob.__table__.update().where(AnalysisJob.id == job.id)
               .values(status='RUNNING', attempt_token='lease-token', phase='TESTING',
                       attempt_no=1, lease_expires_at=utcnow() - timedelta(seconds=5)))
    db.commit()
    db.add(JudgeAttempt(job_id=job.id, attempt_no=1, status='RUNNING', execution_mode='LOCAL'))
    db.commit()
    spawned = local.spawn(['sleep', '30'], judge_work_root)
    marker_path(job.id).write_text(Marker(job_id=job.id, attempt_token='lease-token',
                                          pid=spawned.process.pid, pgid=spawned.pgid,
                                          started_at=time.time()).to_json())
    assert recovery.recover_expired(db.bind) == 1
    spawned.process.wait(timeout=5)
    assert spawned.process.returncode is not None  # the stale program is gone, not just re-queued
    db.expire_all()
    job = db.get(AnalysisJob, job.id)
    assert job.status == 'PENDING' and job.phase == 'RETRY_WAIT'
    assert job.attempt_token is None and job.automatic_retries_used == 1
    attempt = db.scalar(select(JudgeAttempt).where(JudgeAttempt.job_id == job.id))
    assert attempt.status == 'ABORTED' and attempt.failure_code == 'LEASE_EXPIRED'


def test_late_starter_cannot_run_after_recovery_won_the_lock(client, demo, auth, db, local_mode, tmp_path,
                                                             judge_work_root):
    """RV01/AC26: a paused old starter must not create or start the student program."""
    headers = auth()
    submission_id = _submit(client, headers, demo)
    job = db.scalar(select(AnalysisJob).where(AnalysisJob.submission_id == int(submission_id)))
    token = 'original-token'
    db.execute(AnalysisJob.__table__.update().where(AnalysisJob.id == job.id)
               .values(status='RUNNING', attempt_token=token, phase='TESTING', attempt_no=1,
                       lease_expires_at=utcnow() - timedelta(seconds=5)))
    db.commit()

    marker = tmp_path / 'late-start.txt'
    source = f"open({str(marker)!r}, 'w').write('ran')\nprint(0)\n"
    from sqlalchemy.orm import Session

    def verify() -> bool:
        with Session(db.bind) as fresh:
            row = fresh.execute(select(AnalysisJob.status, AnalysisJob.attempt_token, AnalysisJob.phase)
                                .where(AnalysisJob.id == job.id)).first()
        return row is not None and row[0] == 'RUNNING' and row[1] == token and row[2] != 'RECOVERING'

    real_gate = SUPERVISOR.gate(job.id, token, verify)

    def stale_gate(spawned):
        time.sleep(0.6)  # the old starter is paused while recovery runs
        return real_gate(spawned)

    outcome = {}

    def stale_starter():
        try:
            outcome['result'] = local.execute(source, 'python3', [local.CaseInput(1, '', '0\n')], 1000,
                                              gate=stale_gate)
        except BaseException as error:  # noqa: BLE001 - recorded for the assertion message
            outcome['error'] = error

    thread = threading.Thread(target=stale_starter)
    thread.start()
    time.sleep(0.2)
    assert recovery.recover_job(db.bind, job.id) == 'requeued'
    thread.join(10)
    assert isinstance(outcome.get('error'), local.OwnershipLost), outcome
    assert not marker.exists()
    db.expire_all()
    assert db.get(AnalysisJob, job.id).status == 'PENDING'


def test_missing_runtime_is_a_configuration_failure_not_endless_queue(client, demo, auth, db, local_mode):
    headers = auth()
    suite_item = _item(demo)
    from app.db.models import AssignmentItem, TestSuite
    assignment_item = db.get(AssignmentItem, int(suite_item))
    suite = db.get(TestSuite, assignment_item.test_suite_id)
    suite.allowed_languages = ['rust']
    db.commit()
    response = client.post(f'/api/v1/assignment-items/{suite_item}/submissions', headers=headers,
                           json={'content': 'fn main(){}', 'language': 'rust',
                                 'client_request_id': uuid.uuid4().hex})
    assert response.status_code == 409
    assert response.json()['code'] in {'UNSUPPORTED_LANGUAGE', 'JUDGE_CONFIGURATION_UNSUPPORTED'}


def test_compilation_error_keeps_counts_without_resources(client, demo, auth, db, local_mode):
    headers = auth()
    submission_id = _submit(client, headers, demo, content='def broken(:\n')
    assert Scheduler(db.bind, mode='LOCAL', concurrency=1).run_once() == 1
    detail = client.get(f'/api/v1/submissions/{submission_id}', headers=headers).json()
    assert detail['result']['verdict'] == 'COMPILATION_ERROR'
    assert detail['result']['executed_cases'] == 0 and detail['result']['total_cases'] == 5
    assert detail['result']['measurement_status'] == 'NOT_EXECUTED'
    assert detail['result']['compiler_message']
    assert detail['job']['can_retry'] is False


def test_rejudge_then_local_execution_clears_failure(client, demo, auth, db, local_mode):
    headers = auth()
    submission_id = _submit(client, headers, demo)
    job = db.scalar(select(AnalysisJob).where(AnalysisJob.submission_id == int(submission_id)))
    job.status = 'FAILED'
    job.phase = 'FINISHED'
    job.finished_at = utcnow() - timedelta(seconds=120)
    db.commit()
    response = client.post(f'/api/v1/submissions/{submission_id}/rejudge', headers=headers,
                           json={'client_request_id': uuid.uuid4().hex})
    assert response.status_code == 202
    assert Scheduler(db.bind, mode='LOCAL', concurrency=1).run_once() == 1
    detail = client.get(f'/api/v1/submissions/{submission_id}', headers=headers).json()
    assert detail['job_status'] == 'SUCCEEDED' and detail['result']['verdict'] == 'ACCEPTED'
    assert detail['job']['recovery_cycle_no'] == 1


def test_node_and_claim_locks_are_independent(db, demo, local_mode):
    """AC30/RV05: holding the node dispatch lock must not block the claim transaction lock."""
    from sqlalchemy import text
    from app.judge import locks

    locks.check_namespace()
    engine = db.bind
    first = engine.connect().execution_options(isolation_level='AUTOCOMMIT')
    second = engine.connect().execution_options(isolation_level='AUTOCOMMIT')
    try:
        assert locks.try_session_lock(first, locks.SCHEDULER_MAIN) is True
        assert locks.try_session_lock(second, locks.SCHEDULER_MAIN) is False  # one scheduler only
        # A different key is free, so the claim lock is not self-blocked by the main lock.
        assert second.scalar(text('SELECT pg_try_advisory_lock(:a,:b)'),
                             {'a': locks.CLAIM[0], 'b': locks.CLAIM[1]}) is True
        second.execute(text('SELECT pg_advisory_unlock(:a,:b)'), {'a': locks.CLAIM[0], 'b': locks.CLAIM[1]})
        locks.session_unlock(first, locks.SCHEDULER_MAIN)
        assert locks.try_session_lock(second, locks.SCHEDULER_MAIN) is True
        locks.session_unlock(second, locks.SCHEDULER_MAIN)
    finally:
        first.close()
        second.close()


def test_unimplemented_sandbox_mode_is_refused_instead_of_mislabelled(client, demo, auth, db, monkeypatch):
    """No LINUX_SANDBOX driver: refuse to schedule and refuse to accept new jobs."""
    from app.judge import config
    assert config.driver_available('LOCAL') and config.driver_available('MOCK')
    assert config.driver_available('LINUX_SANDBOX') is False
    with pytest.raises(RuntimeError):
        Scheduler(db.bind, mode='LINUX_SANDBOX', concurrency=1)
    from scripts.run_judge import main as cli
    assert cli(['--once', '--mode', 'LINUX_SANDBOX']) == 2

    monkeypatch.setenv('JUDGE_EXECUTION_MODE', 'LINUX_SANDBOX')
    response = client.post(f"/api/v1/assignment-items/{_item(demo)}/submissions", headers=auth(),
                           json={'content': 'print(1)', 'language': 'python3',
                                 'client_request_id': uuid.uuid4().hex})
    assert response.status_code == 409
    assert response.json()['code'] == 'JUDGE_CONFIGURATION_UNSUPPORTED'
    assert db.scalar(select(AnalysisJob)) is None


def test_service_pause_keeps_jobs_queued_and_resumes_after_switch(client, demo, auth, db, local_mode, monkeypatch):
    """A paused service must stop claiming work without discarding accepted jobs."""
    headers = auth()
    submission_id = _submit(client, headers, demo)
    monkeypatch.setenv('JUDGE_SERVICE_PAUSED', '1')
    scheduler = Scheduler(db.bind, mode='LOCAL', concurrency=1)
    assert scheduler.claim() is None
    assert scheduler.run_once() == 0
    db.expire_all()
    job = db.scalar(select(AnalysisJob).where(AnalysisJob.submission_id == int(submission_id)))
    assert job.status == 'PENDING'

    monkeypatch.setenv('JUDGE_SERVICE_PAUSED', '0')
    assert scheduler.run_once() == 1
    db.expire_all()
    assert db.get(AnalysisJob, job.id).status == 'SUCCEEDED'
