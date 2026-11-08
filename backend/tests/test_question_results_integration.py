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


def course_snapshot(db,scope,**overrides):
    from app.analysis.course_results import create_snapshot
    from app.analysis.integration_router import CourseSnapshotCreate
    body=CourseSnapshotCreate(request_id=overrides.pop('request_id',uuid4().hex),reason='合成测试：课程章节证据',**overrides)
    result=create_snapshot(db,scope[2].course_id,scope[0],body)
    db.commit()
    return result


def test_course_bridge_runs_both_real_models_and_projects_only_self(db,scope,client,auth):
    from app.analysis.framework.ability_b0_line import create_batch,project
    from app.analysis.framework.service import ability_input_view,batch_view
    fixed=create(db,scope);db.commit()
    source=course_snapshot(db,scope)
    assert source['source_count']==1 and source['known_count']==1 and source['total']==24
    for model in ('b0','d1'):
        batch=create_batch(db,scope[2].course_id,scope[0],dict(mode='REAL_INPUT',seed=1,
            request_id=uuid4().hex,source_batch_id=source['id']),model=model)
        frozen=ability_input_view(db,int(batch['id']),scope[0])
        payload=frozen['payload'] if model=='b0' else frozen['payload']['learning_input']
        assert payload['source_kind']=='DATABASE'
        assert len(payload['scope']['expected_pairs'])==24
        assert len(payload['grades'])==1
        for _ in range(20):
            if not process_one(db):break
        result=batch_view(db,int(batch['id']),scope[0])['steps'][0]
        assert result['status']=='SUCCEEDED' and not result['result']['is_mock']
        own=project(db,scope[2].course_id,scope[1][0],model=model)
        assert own['status']=='OK' and len(own['estimates'])==11
        assert {e['object_key'] for e in own['estimates']}=={f'student-{scope[1][0].id}'}
        assert all('evidence_item_keys' not in e for e in own['estimates'])
        no_grade=project(db,scope[2].course_id,scope[1][1],model=model)
        assert no_grade['status']=='INSUFFICIENT_DATA'
        assert all(e['value'] is None for e in no_grade['estimates'])
        assert project(db,scope[2].course_id,scope[1][0],demo=True,model=model)['status']=='NO_DEMO_ANALYSIS'
    student=auth()
    assert client.get(f"/api/v1/analysis/batches/{source['id']}/input",headers=student).status_code==403
    assert client.get(f'/api/v1/analysis/courses/{scope[2].course_id}/student-ability/status',headers=student).status_code==403


def test_course_bridge_latest_per_assignment_and_idempotent_historical_selection(db,scope):
    first=create(db,scope);db.commit()
    scope[4].passed_cases=0;db.commit()
    second=create(db,scope);db.commit()
    source=course_snapshot(db,scope,request_id='stable-course')
    from app.db.models.analytics import AnalysisBatch
    artifact,data=qr._payload(db,db.get(AnalysisBatch,int(source['id'])))
    assert [s['batch_id'] for s in data['sources']]==[second['id']]
    assert data['ability_input_v2']['grades'][0]['normalized_score']=='0'
    scope[4].passed_cases=3;db.commit();create(db,scope);db.commit()
    assert course_snapshot(db,scope,request_id='stable-course')==source
    historical=course_snapshot(db,scope,source_batch_ids=[first['id']])
    _,old=qr._payload(db,db.get(AnalysisBatch,int(historical['id'])))
    assert old['ability_input_v2']['grades'][0]['normalized_score']=='0.8'
    with pytest.raises(AppError) as err:course_snapshot(db,scope,source_batch_ids=[first['id'],second['id']])
    assert err.value.code=='DUPLICATE_ASSIGNMENT_SOURCE'


def test_course_bridge_rejects_legacy_missing_metadata_and_corrupt_evidence(db,scope):
    from app.db.models.analytics import AnalysisBatch,AnalysisInputSnapshot
    fixed=create(db,scope);db.commit()
    batch=db.get(AnalysisBatch,int(fixed['id']));artifact,data=qr._payload(db,batch)
    legacy=dict(data);legacy.pop('ability_input_v2')
    root=db.scalar(select(AnalysisInputSnapshot).where(AnalysisInputSnapshot.batch_id==batch.id,AnalysisInputSnapshot.scope=='ROOT'))
    from app.analysis.framework.contracts import digest
    root.payload=legacy;root.input_hash=digest(legacy)
    artifact.payload=dict(artifact.payload,input_hash=root.input_hash,payload=legacy);artifact.output_hash=digest(artifact.payload);db.commit()
    with pytest.raises(AppError) as err:course_snapshot(db,scope)
    assert err.value.code=='CHAPTER_METADATA_REQUIRED';db.rollback()
    artifact.output_hash='0'*64;db.commit()
    with pytest.raises(AppError) as err:course_snapshot(db,scope)
    assert err.value.code=='QUESTION_RESULTS_INVALID'


def test_course_bridge_http_scope_validation_and_missing_sources(client,auth,db,scope):
    teacher=auth('demo.teacher');student=auth();cid=scope[2].course_id
    path=f'/api/v1/analysis/courses/{cid}/course-results'
    body=dict(request_id='course-http',reason='合成测试课程范围')
    assert client.post(path,headers=student,json=body).status_code==403
    assert client.post(path,headers=teacher,json=body).status_code==409
    create(db,scope);db.commit()
    assert client.post(path,headers=teacher,json=dict(body,source_batch_ids=['999999999'])).status_code==404
    for ids in (['1','1'],['9223372036854775808'],['0']):
        assert client.post(path,headers=teacher,json=dict(body,source_batch_ids=ids)).status_code==422
    response=client.post(path,headers=teacher,json=body)
    assert response.status_code==201,response.text
    assert response.json()['is_mock'] is False


def test_course_bridge_combines_assignments_and_rejects_mapping_version_conflicts(db,scope):
    from app.db.models.analytics import AnalysisBatch,AnalysisInputSnapshot
    from app.analysis.framework.contracts import digest
    first=create(db,scope);db.commit()
    other=db.scalar(select(Assignment).where(Assignment.course_id==scope[2].course_id,Assignment.id!=scope[2].id))
    other.submission_status='CLOSED';other.published_at=utcnow()-timedelta(days=3);other.submission_deadline=utcnow()-timedelta(days=1);db.commit()
    second=qr.create_snapshot(db,other.course_id,scope[0],SnapshotCreate(request_id=uuid4().hex,
        assignment_id=str(other.id),reason='第二次合成作业范围'));db.commit()
    course=course_snapshot(db,scope)
    _,payload=qr._payload(db,db.get(AnalysisBatch,int(course['id'])))
    assert course['source_count']==2 and course['student_count']==6
    assert len(payload['ability_input_v2']['scope']['assignment_ids'])==2
    assert course['total']==first['total']+second['total']
    artifact,data=qr._payload(db,db.get(AnalysisBatch,int(second['id'])))
    from copy import deepcopy
    changed=deepcopy(data);changed['ability_input_v2']['chapter_mapping_version']='different-version'
    root=db.scalar(select(AnalysisInputSnapshot).where(AnalysisInputSnapshot.batch_id==int(second['id']),AnalysisInputSnapshot.scope=='ROOT'))
    root.payload=changed;root.input_hash=digest(changed)
    artifact.payload=dict(artifact.payload,payload=changed,input_hash=root.input_hash);artifact.output_hash=digest(artifact.payload);db.commit()
    with pytest.raises(AppError) as err:course_snapshot(db,scope)
    assert err.value.code=='CHAPTER_VERSION_CONFLICT'
