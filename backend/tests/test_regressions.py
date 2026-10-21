from decimal import Decimal
import uuid
from sqlalchemy import text,select
from app.db.base import utcnow
from app.db.models import TestSuite as SuiteModel,AssignmentItem,AnalysisJob


def test_readiness_rejects_database_from_different_migration_head(client,db):
    original=db.scalar(text('SELECT version_num FROM alembic_version'))
    try:
        db.execute(text("UPDATE alembic_version SET version_num='unrecognized'"));db.commit()
        response=client.get('/api/v1/ready')
        assert response.status_code==503
    finally:
        db.execute(text('UPDATE alembic_version SET version_num=:version'),{'version':original});db.commit()


def test_worker_uses_submitted_test_suite_snapshot(client,demo,auth,db,monkeypatch):
    from app.analysis import worker
    original_judge=worker.judge
    captured=[]
    item_id=int(next(x['id'] for x in demo[0]['items'] if x['type']=='PROGRAMMING'))
    response=client.post(f'/api/v1/assignment-items/{item_id}/submissions',headers=auth(),
        json={'content':'print(1)','language':'python3','client_request_id':uuid.uuid4().hex})
    assert response.status_code==202
    job=db.scalar(select(AnalysisJob));original_id=job.parameters['test_suite_id']
    item=db.get(AssignmentItem,item_id)
    old=db.get(SuiteModel,item.test_suite_id)
    new=SuiteModel(problem_version_id=old.problem_version_id,version_no=old.version_no+1,
        cpu_limit_ms=1000,memory_limit_kib=262144,allowed_languages=['python3'],frozen_at=utcnow())
    db.add(new);db.flush();item.test_suite_id=new.id;db.commit()
    def observe(input):
        captured.append(input.test_suite_id)
        return original_judge(input)
    monkeypatch.setattr(worker,'judge',observe)
    worker.process_pending_jobs(db,20)
    assert captured==[original_id]


def test_idempotency_tokens_are_case_sensitive(client,demo,auth):
    headers=auth()
    item=next(x['id'] for x in demo[0]['items'] if x['type']=='PROGRAMMING')
    def submit(key):
        return client.post(f'/api/v1/assignment-items/{item}/submissions',headers=headers,
            json={'content':'print(1)','language':'python3','client_request_id':key})
    first=submit('ReqA');second=submit('reqa')
    assert first.status_code==second.status_code==202
    assert first.json()['submission_id']!=second.json()['submission_id']
    assert second.json()['version_no']==2 and second.json()['replayed'] is False


def test_cli_recovers_interrupted_mock_job_without_duplicate_result(client,demo,auth,db):
    import json
    import subprocess
    import sys
    from pathlib import Path
    from app.db.models import JudgeResult
    item=next(x['id'] for x in demo[0]['items'] if x['type']=='PROGRAMMING')
    response=client.post(f'/api/v1/assignment-items/{item}/submissions',headers=auth(),
        json={'content':'print(1)','language':'python3','client_request_id':uuid.uuid4().hex})
    assert response.status_code==202
    job=db.scalar(select(AnalysisJob));job.status='RUNNING';job.started_at=utcnow();db.commit()
    command=[sys.executable,'-m','scripts.process_mock_jobs','--recover-running']
    result=subprocess.run(command,cwd=Path(__file__).resolve().parents[1],capture_output=True,text=True,timeout=20)
    assert result.returncode==0 and json.loads(result.stdout)['processed']==1
    db.expire_all()
    assert db.get(AnalysisJob,job.id).status=='SUCCEEDED'
    assert db.scalar(select(JudgeResult).where(JudgeResult.job_id==job.id)) is not None
