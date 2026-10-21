from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import uuid
import pytest
from sqlalchemy import select,func,event
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from app.db.models import User,Submission,AnalysisJob,Assignment,AssignmentItem,JudgeResult,CourseMember
from app.db.base import utcnow
from app.student.schemas import SubmissionInput
from app.student.service import accept_submission


def test_concurrent_retries_and_new_versions_are_serialized(db,demo):
    engine=db.bind
    uid=db.scalar(select(User.id).where(User.login_name=='demo.student01'))
    item=int(next(x['id'] for x in demo[0]['items'] if x['type']=='PROGRAMMING'))
    key=uuid.uuid4().hex
    db.commit()
    def run(key):
        with Session(engine,expire_on_commit=False) as session:
            user=session.get(User,uid)
            return accept_submission(session,item,user,SubmissionInput(content='print(1)',language='python3',client_request_id=key))
    with ThreadPoolExecutor(max_workers=4) as pool:
        retries=list(pool.map(run,[key]*4))
        versions=list(pool.map(run,[uuid.uuid4().hex for _ in range(4)]))
    assert len({r['submission_id'] for r in retries})==1
    assert sum(not r['replayed'] for r in retries)==1
    assert sorted(r['version_no'] for r in versions)==[2,3,4,5]
    assert db.scalar(select(func.count()).select_from(Submission))==5
    assert db.scalar(select(func.count()).select_from(AnalysisJob))==5


def test_task_write_failure_rolls_back_submission(client,demo,auth,db):
    headers={**auth(),'Origin':'http://localhost:5173'}
    item=next(x['id'] for x in demo[0]['items'] if x['type']=='PROGRAMMING')
    def reject_task(mapper,connection,target):
        raise RuntimeError('simulated database write failure')
    event.listen(AnalysisJob,'before_insert',reject_task)
    try:
        response=client.post(f'/api/v1/assignment-items/{item}/submissions',headers=headers,
            json={'content':'print(1)','language':'python3','client_request_id':uuid.uuid4().hex})
    finally:
        event.remove(AnalysisJob,'before_insert',reject_task)
    assert response.status_code==500
    assert 'simulated database' not in response.text
    assert response.headers['X-Request-ID']==response.json()['request_id']
    assert response.headers['Access-Control-Allow-Origin']=='http://localhost:5173'
    db.rollback()
    assert db.scalar(select(func.count()).select_from(Submission))==0
    assert db.scalar(select(func.count()).select_from(AnalysisJob))==0


def test_postgresql_rejects_duplicate_student_number_and_missing_foreign_key(db,demo):
    user=db.scalar(select(User).where(User.login_name=='demo.student01'))
    db.add(User(login_name='duplicate',student_no=user.student_no,full_name='重名允许但学号不能重复'))
    with pytest.raises(IntegrityError):db.flush()
    db.rollback()
    db.add(CourseMember(course_id=9223372036854775806,user_id=user.id,role='STUDENT'))
    with pytest.raises(IntegrityError):db.flush()
    db.rollback()


def test_readiness_uses_migration_and_login_not_forged_role(client,demo,auth):
    assert client.get('/api/v1/ready').status_code==200
    response=client.post('/api/v1/auth/login',json={'login_name':'demo.student01','password':demo[1],'role':'TEACHER'})
    assert response.status_code==422
    headers=auth('demo.teacher')
    item=next(x['id'] for x in demo[0]['items'] if x['type']=='PROGRAMMING')
    response=client.post(f'/api/v1/assignment-items/{item}/submissions',headers=headers,
        json={'content':'print(1)','language':'python3','client_request_id':uuid.uuid4().hex})
    assert response.status_code==403


def test_worker_failure_records_error_without_fake_result(client,demo,auth,db,monkeypatch):
    from app.analysis import worker
    item=next(x['id'] for x in demo[0]['items'] if x['type']=='PROGRAMMING')
    response=client.post(f'/api/v1/assignment-items/{item}/submissions',headers=auth(),
        json={'content':'print(1)','language':'python3','client_request_id':uuid.uuid4().hex})
    def broken_adapter(input):raise ValueError('internal secret must not leak')
    monkeypatch.setattr(worker,'judge',broken_adapter)
    assert worker.process_pending_jobs(db,20)==1
    job=db.scalar(select(AnalysisJob))
    assert job.status=='FAILED' and 'secret' not in job.error_message
    assert db.scalar(select(func.count()).select_from(JudgeResult))==0


@pytest.mark.parametrize('model_name,field', [
    ('AssignmentItem', 'sort_order'), ('AssignmentItem', 'required_reviewers'),
    ('TestCase', 'sort_order'), ('RubricItem', 'sort_order'), ('Rubric', 'version_no'),
])
def test_postgresql_preserves_nonnegative_integer_constraints(db, demo, model_name, field):
    from app.db import models
    model = getattr(models, model_name)
    row = db.scalar(select(model))
    assert row is not None
    setattr(row, field, -1)
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


@pytest.mark.parametrize('resource', ['cpu_time_ms', 'memory_kib'])
def test_postgresql_rejects_negative_measured_judge_resources(client, demo, auth, db, resource):
    from app.analysis.worker import process_pending_jobs
    item = next(x['id'] for x in demo[0]['items'] if x['type'] == 'PROGRAMMING')
    response = client.post(f'/api/v1/assignment-items/{item}/submissions', headers=auth(),
        json={'content': 'print(1)', 'language': 'python3', 'client_request_id': uuid.uuid4().hex})
    assert response.status_code == 202
    assert process_pending_jobs(db, 20) == 1
    result = db.scalar(select(JudgeResult))
    result.is_mock = False
    setattr(result, resource, -1)
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()
