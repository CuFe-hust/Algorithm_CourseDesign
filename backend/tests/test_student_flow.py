from datetime import timedelta
import uuid
import pytest
from sqlalchemy import select, func
from app.db.base import utcnow
from app.db.models import (User, CourseMember, Assignment, AssignmentItem, AssignmentParticipant,
    Submission, AnalysisJob, JudgeResult, AuthSession)


def programming_item(demo):
    return next(x['id'] for x in demo[0]['items'] if x['type']=='PROGRAMMING')


def submit(client, headers, item, key=None, content='print("中文")'):
    return client.post(f'/api/v1/assignment-items/{item}/submissions', headers=headers,
        json={'content':content, 'language':'python3', 'client_request_id':key or uuid.uuid4().hex})


def test_login_rejects_bad_password_and_logout_revokes_token(client, demo, auth):
    denied = client.post('/api/v1/auth/login', json={'login_name':'demo.teacher','password':'incorrect'})
    assert denied.status_code == 401
    headers = auth()
    assert client.get('/api/v1/courses', headers=headers).status_code == 200
    assert client.post('/api/v1/auth/logout', headers=headers).status_code == 200
    assert client.get('/api/v1/courses', headers=headers).status_code == 401


def test_disabled_and_expired_sessions_cannot_access(client, demo, auth, db):
    headers = auth()
    user = db.scalar(select(User).where(User.login_name=='demo.student01'))
    user.status='DISABLED'; db.commit()
    assert client.get('/api/v1/courses', headers=headers).status_code == 401
    assert client.post('/api/v1/auth/login', json={'login_name':user.login_name,'password':demo[1]}).status_code == 401
    user.status='ACTIVE'; db.commit()
    headers = auth()
    for session in db.scalars(select(AuthSession).where(AuthSession.user_id==user.id)):
        session.expires_at=utcnow()-timedelta(seconds=1)
    db.commit()
    assert client.get('/api/v1/courses', headers=headers).status_code == 401


def test_item_hides_reference_hidden_tests_and_other_identity(client, demo, auth):
    item=programming_item(demo)
    assert client.get(f'/api/v1/assignment-items/{item}').status_code == 401
    response=client.get(f'/api/v1/assignment-items/{item}',headers=auth())
    assert response.status_code == 200
    body=response.json()
    assert body['title']=='活动安排问题' and isinstance(body['id'],str)
    assert '题目' not in body.get('reference_solution','')
    for key in ['reference_solution','reference_solutions','test_cases','expected_output','created_by','student_id']:
        assert key not in body
    assert body['allowed_languages']==['python3']


def test_submission_persists_versions_isolation_and_atomic_job(client, demo, auth, db):
    headers=auth(); item=programming_item(demo)
    a=submit(client,headers,item); b=submit(client,headers,item)
    assert a.status_code==202 and b.status_code==202
    assert a.json()['version_no']==1 and b.json()['version_no']==2
    detail=client.get('/api/v1/submissions/'+a.json()['submission_id'],headers=headers)
    assert detail.status_code==200 and detail.json()['content']=='print("中文")'
    assert detail.json()['result'] is None and detail.json()['job_status']=='PENDING'
    assert client.get('/api/v1/submissions/'+a.json()['submission_id'],headers=auth('demo.student02')).status_code==404
    assert db.scalar(select(func.count()).select_from(Submission))==2
    assert db.scalar(select(func.count()).select_from(AnalysisJob))==2
    teacher=auth('demo.teacher')
    response=client.get('/api/v1/teacher/courses/'+demo[0]['course_id']+'/submissions',headers=teacher)
    assert response.status_code==200 and response.json()['total']==2
    assert client.get('/api/v1/teacher/courses/'+demo[0]['course_id']+'/submissions',headers=headers).status_code==403


def test_idempotency_replays_once_and_conflicting_payload_returns_409(client,demo,auth,db):
    headers=auth(); item=programming_item(demo); key=uuid.uuid4().hex
    a=submit(client,headers,item,key); b=submit(client,headers,item,key)
    assert a.status_code==b.status_code==202
    assert a.json()['submission_id']==b.json()['submission_id'] and b.json()['replayed'] is True
    assert submit(client,headers,item,key,content='different').status_code==409
    assert db.scalar(select(func.count()).select_from(Submission))==1
    assert db.scalar(select(func.count()).select_from(AnalysisJob))==1


def test_subjective_submission_preserves_formula_without_fake_score(client,demo,auth,db):
    headers=auth(); item=next(x['id'] for x in demo[0]['items'] if x['type']=='ALGORITHM_ANALYSIS')
    content='证明 $T(n)=O(n\\log n)$；边界：空数组。'
    response=client.post(f'/api/v1/assignment-items/{item}/submissions',headers=headers,
        json={'content':content,'client_request_id':uuid.uuid4().hex})
    assert response.status_code==202 and response.json()['job_status']=='AWAITING_REVIEW'
    detail=client.get('/api/v1/submissions/'+response.json()['submission_id'],headers=headers).json()
    assert detail['content']==content and detail['result'] is None
    assert db.scalar(select(func.count()).select_from(AnalysisJob))==0


def test_membership_and_assignment_roster_enforced(client,demo,auth,db):
    headers=auth(); item=programming_item(demo)
    user=db.scalar(select(User).where(User.login_name=='demo.student01'))
    member=db.scalar(select(CourseMember).where(CourseMember.user_id==user.id)); member.status='INACTIVE';db.commit()
    assert client.get(f'/api/v1/assignment-items/{item}',headers=headers).status_code==404
    assert submit(client,headers,item).status_code==404
    member.status='ACTIVE'
    assignment_id=db.get(AssignmentItem,int(item)).assignment_id
    participant=db.scalar(select(AssignmentParticipant).where(AssignmentParticipant.student_id==user.id,AssignmentParticipant.assignment_id==assignment_id))
    db.delete(participant);db.commit()
    assert client.get(f'/api/v1/assignment-items/{item}',headers=headers).status_code==404
    assert submit(client,headers,item).status_code==404


def test_deadline_rejects_new_submission_but_preserves_accepted_retry(client,demo,auth,db):
    headers=auth();item=programming_item(demo);key=uuid.uuid4().hex
    first=submit(client,headers,item,key)
    assignment=db.get(Assignment,db.get(AssignmentItem,int(item)).assignment_id)
    assignment.submission_deadline=utcnow()-timedelta(seconds=1);db.commit()
    assert submit(client,headers,item).status_code==409
    assert submit(client,headers,item,key).json()['submission_id']==first.json()['submission_id']


@pytest.mark.parametrize('payload',[
    {'content':'  ','language':'python3','client_request_id':'empty'},
    {'content':'print(1)','language':'unsupported','client_request_id':'bad-language'},
    {'content':'x'*65537,'language':'python3','client_request_id':'too-long'},
    {'content':'print(1)','language':'python3','client_request_id':'extra','student_id':'2'},
])
def test_invalid_submission_rejected_without_partial_write(client,demo,auth,db,payload):
    response=client.post(f'/api/v1/assignment-items/{programming_item(demo)}/submissions',headers=auth(),json=payload)
    assert response.status_code==422
    assert db.scalar(select(func.count()).select_from(Submission))==0
    assert db.scalar(select(func.count()).select_from(AnalysisJob))==0


def test_mock_result_persists_and_is_never_measured_or_formal_grade(client,demo,auth,db):
    from app.analysis.worker import process_pending_jobs
    headers=auth();response=submit(client,headers,programming_item(demo))
    assert response.status_code==202
    assert process_pending_jobs(db,20)==1
    assert process_pending_jobs(db,20)==0
    result=client.get('/api/v1/submissions/'+response.json()['submission_id'],headers=headers).json()
    assert result['job_status']=='SUCCEEDED'
    assert result['result']['verdict']=='MOCK_ACCEPTED'
    assert result['result']['is_mock'] is True
    assert result['result']['cpu_time_ms'] is None and result['result']['memory_kib'] is None
    assert 'score' not in result['result']
    assert db.scalar(select(func.count()).select_from(JudgeResult))==1


def test_withdrawal_retains_version_and_cancels_pending_task(client,demo,auth,db):
    from app.analysis.worker import process_pending_jobs
    headers=auth(); response=submit(client,headers,programming_item(demo)); sid=response.json()['submission_id']
    assert client.post(f'/api/v1/submissions/{sid}/withdraw',headers=headers).status_code==200
    process_pending_jobs(db,20)
    detail=client.get(f'/api/v1/submissions/{sid}',headers=headers).json()
    assert detail['status']=='WITHDRAWN' and detail['job_status']=='CANCELLED' and detail['result'] is None
    assert db.scalar(select(func.count()).select_from(Submission))==1
