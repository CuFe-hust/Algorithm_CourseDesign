"""AC34 / RV09: bounded auxiliary cleanup never deletes business history."""
from datetime import timedelta

from sqlalchemy import select

from app.db.base import utcnow
from app.db.models import AuthSession, JudgeResult, RequestRateLimit, Submission, User
from app.judge import maintenance


def test_auxiliary_cleanup_is_bounded_and_preserves_business_history(db, demo):
    now = utcnow()
    user = db.scalar(select(User).where(User.login_name == 'demo.student01'))
    db.add(AuthSession(user_id=user.id, token_hash='expired-token', expires_at=now - timedelta(hours=30),
                       last_active_at=now - timedelta(hours=31),
                       absolute_expires_at=now - timedelta(hours=25)))
    live = AuthSession(user_id=user.id, token_hash='live-token', expires_at=now + timedelta(hours=1),
                       last_active_at=now, absolute_expires_at=now + timedelta(hours=20))
    db.add(live)
    db.add(RequestRateLimit(bucket='login_account', subject_hash='x' * 64, window_start=now,
                            window_seconds=60, counter=1, expires_at=now - timedelta(minutes=5)))
    item_id = int(demo[0]['items'][0]['id'])
    submission = Submission(assignment_item_id=item_id, student_id=user.id, version_no=1, content='print(1)',
                            language='python3', submitted_at=now - timedelta(days=40),
                            client_request_id='cleanup-test')
    db.add(submission)
    db.commit()
    from app.db.models import AnalysisJob
    job = AnalysisJob(submission_id=submission.id, status='SUCCEEDED', phase='FINISHED', parameters={})
    db.add(job)
    db.flush()
    result = JudgeResult(job_id=job.id, submission_id=submission.id, verdict='ACCEPTED', is_mock=False,
                         algorithm_name='local_judge', algorithm_version='1', cpu_time_ms=None,
                         memory_kib=None, message='通过 5 / 5 个测试点', passed_cases=5, executed_cases=5,
                         total_cases=5, execution_mode='LOCAL', runtime_profile='local-dev-v1',
                         measurement_status='UNAVAILABLE_LOCAL', compiler_message='x' * 500)
    db.add(result)
    db.commit()
    result.created_at = now - timedelta(days=45)
    db.commit()

    report = maintenance.purge_all(db.bind, now)
    assert report['sessions'] == 1 and report['rate_limits'] == 1 and report['diagnostics'] == 1
    db.expire_all()
    assert db.scalar(select(AuthSession).where(AuthSession.token_hash == 'live-token')) is not None
    assert db.scalar(select(AuthSession).where(AuthSession.token_hash == 'expired-token')) is None
    result = db.get(JudgeResult, result.id)
    assert result.compiler_message is None and result.diagnostics_expired_at is not None
    assert result.verdict == 'ACCEPTED' and result.passed_cases == 5
    assert db.get(Submission, submission.id) is not None


def test_cli_entrypoint_runs_maintenance(db, demo):
    import pytest
    from scripts.run_judge import main
    db.commit()
    assert main(['--recover']) == 0
    assert main(['--purge-aux']) == 0
    with pytest.raises(SystemExit):
        main([])
