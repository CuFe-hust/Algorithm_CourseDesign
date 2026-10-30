"""Cross-module evidence, immutable snapshot and role-projection integration."""
from datetime import timedelta
from decimal import Decimal
from uuid import uuid4
import pytest
from sqlalchemy import select
from app.db.base import utcnow
from app.db.models import User,Assignment,AssignmentItem,Submission,AnalysisJob,JudgeResult,TestCase as Case
from app.analysis import question_results as qr
from app.analysis.integration_router import SnapshotCreate
from app.analysis.framework.service import create_ability_batch
from app.analysis.framework.runner import process_one
from app.core.errors import AppError

@pytest.fixture
def scope(db,demo,monkeypatch):
    monkeypatch.setenv('JUDGE_EXECUTION_MODE','LOCAL')
    teacher=db.scalar(select(User).where(User.login_name=='demo.teacher'))
    students=list(db.scalars(select(User).where(User.login_name.like('demo.student%')).order_by(User.id)))
    a=db.scalar(select(Assignment).order_by(Assignment.id.desc()));a.published_at=utcnow()-timedelta(days=3);a.submission_deadline=utcnow()-timedelta(days=1);a.submission_status='CLOSED'
    item=db.scalar(select(AssignmentItem).where(AssignmentItem.assignment_id==a.id,AssignmentItem.test_suite_id.is_not(None)))
    s=Submission(assignment_item_id=item.id,student_id=students[0].id,version_no=1,content='print(1)',language='python3',submitted_at=utcnow()-timedelta(days=2),client_request_id=uuid4().hex)
    db.add(s);db.flush();job=AnalysisJob(submission_id=s.id,kind='JUDGE',status='SUCCEEDED',algorithm_name='local_judge');db.add(job);db.flush()
    r=JudgeResult(job_id=job.id,submission_id=s.id,verdict='WRONG_ANSWER',is_mock=False,algorithm_name='local_judge',algorithm_version='1',
        execution_mode='LOCAL',runtime_profile='local-dev-v1',measurement_status='UNAVAILABLE_LOCAL',passed_cases=4,executed_cases=5,total_cases=5,message='Synthetic integration fixture')
    db.add(r);db.commit();return teacher,students,a,item,r


def create(db,scope,key=None):
    return qr.create_snapshot(db,scope[2].course_id,scope[0],SnapshotCreate(request_id=key or uuid4().hex,assignment_id=str(scope[2].id),reason='合成整合测试：固定逐题证据'))


def test_verified_equal_weights_and_missing_remain_separate(db,scope):
    report=create(db,scope);db.commit()
    assert report['known_count']==1 and report['missing_count']==23
    row=next(r for r in report['rows'] if r['normalized_score'] is not None)
    assert Decimal(row['normalized_score'])==Decimal('.8') and row['source']['policy']=='VERIFIED_UNIFORM_CASE_WEIGHTS'
    assert all(r['item_score'] is None for r in report['rows'] if r['normalized_score'] is None)
    assert 'total_score' not in str(report)


def test_unequal_weight_partial_result_is_unavailable_but_full_acceptance_is_proven(db,scope):
    case=db.scalar(select(Case).where(Case.test_suite_id==scope[3].test_suite_id));case.weight=Decimal('.4');db.commit()
    first=create(db,scope);db.commit()
    row=next(r for r in first['rows'] if r['submission_id']==str(scope[4].submission_id))
    assert row['normalized_score'] is None and row['reason']=='WEIGHTED_CASE_EVIDENCE_UNAVAILABLE'
    scope[4].passed_cases=5;scope[4].verdict='ACCEPTED';db.commit();second=create(db,scope);db.commit()
    row=next(r for r in second['rows'] if r['normalized_score'] is not None)
    assert row['normalized_score']=='1' and row['source']['policy']=='ALL_CASES_ACCEPTED'


def test_mock_and_wrong_runtime_results_cannot_become_scores(db,scope):
    scope[4].is_mock=True;scope[4].execution_mode='MOCK';scope[4].runtime_profile='mock-v1';db.commit()
    assert create(db,scope)['known_count']==0;db.rollback()
    scope[4].is_mock=False;scope[4].execution_mode='LOCAL';scope[4].runtime_profile='different-profile';db.commit()
    assert create(db,scope)['known_count']==0


def test_fixed_snapshots_replay_and_do_not_change_with_later_source_updates(db,scope):
    first=create(db,scope,'fixed-id');db.commit();scope[4].passed_cases=3;db.commit()
    replay=create(db,scope,'fixed-id');db.commit();assert replay['id']==first['id'] and replay['output_hash']==first['output_hash']
    second=create(db,scope);db.commit();assert second['id']!=first['id'] and second['output_hash']!=first['output_hash']
    assert qr.snapshot_view(db,int(first['id']),scope[0])['rows']==first['rows']


def test_personal_projection_hides_other_students_and_ability_reads_real_snapshot(db,scope):
    report=create(db,scope);db.commit();personal=qr.snapshot_view(db,int(report['id']),scope[1][0])
    assert len(personal['rows'])==4 and personal['known_count']==1
    assert all('student_id' not in r and 'student_name' not in r for r in personal['rows'])
    assert all(q['known']<=1 for q in personal['per_item'])
    batch=create_ability_batch(db,scope[2].course_id,scope[0],dict(mode='REAL_INPUT',seed=1,request_id=uuid4().hex,source_batch_id=report['id']))
    for _ in range(10):
        if not process_one(db):break
    from app.analysis.framework.service import batch_view
    step=batch_view(db,int(batch['id']),scope[0])['steps'][0]
    assert step['business_status']=='NOT_IMPLEMENTED' and not step['result']['is_mock']


def test_open_scope_is_rejected_and_http_permissions_are_scoped(client,auth,db,scope):
    scope[2].submission_status='OPEN';scope[2].submission_deadline=utcnow()+timedelta(days=1);db.commit()
    with pytest.raises(AppError) as err:create(db,scope)
    assert err.value.code=='QUESTION_SCOPE_NOT_FROZEN';db.rollback()
    student=auth('demo.student01')
    assert client.get(f'/api/v1/analysis/courses/{scope[2].course_id}/workflow-status',headers=student).status_code==403
    assert client.post(f'/api/v1/analysis/courses/{scope[2].course_id}/question-results',headers=student,json=dict(request_id='x',assignment_id=str(scope[2].id),reason='越权测试')).status_code==403


def test_system_errors_and_inconsistent_verdicts_are_not_scores(db,scope):
    scope[4].verdict='SYSTEM_ERROR';db.commit();assert create(db,scope)['known_count']==0;db.rollback()
    scope[4].verdict='ACCEPTED';scope[4].passed_cases=4;db.commit();assert create(db,scope)['known_count']==0
