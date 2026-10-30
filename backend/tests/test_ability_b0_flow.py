from sqlalchemy import select
from app.db.models import User
from app.analysis.framework.runner import process_one


def test_b0_demo_uses_real_algorithm_and_self_only_projection(client, auth, demo, db):
    teacher = auth('demo.teacher')
    student = auth()
    cid = demo[0]['course_id']
    path = f'/api/v1/analysis/courses/{cid}/student-ability/b0-batches'
    assert client.post(path, headers=student, json={'request_id': 'deny'}).status_code == 403
    response = client.post(path, headers=teacher, json={'request_id': 'b0-demo'})
    assert response.status_code == 201, response.text
    batch = response.json()
    assert batch['pipeline'] == 'STUDENT_ABILITY_B0'
    assert len(batch['steps']) == 1
    assert client.post(path, headers=teacher, json={'request_id': 'b0-demo'}).json()['id'] == batch['id']
    inp = client.get(f"/api/v1/analysis/batches/{batch['id']}/input", headers=teacher)
    assert inp.status_code == 200
    before = inp.json()
    for _ in range(30):
        if not process_one(db): break
    complete = client.get(f"/api/v1/analysis/batches/{batch['id']}", headers=teacher).json()
    assert complete['status'] == 'COMPLETE', complete
    artifact = complete['steps'][0]['result']
    assert artifact['implementation_name'] == 'ability_b0'
    assert artifact['input_hash'] == before['input_hash']
    assert artifact['is_mock'] is True
    view = client.get(f'/api/v1/courses/{cid}/my-ability/demo', headers=student)
    assert view.status_code == 200, view.text
    result = view.json()
    assert result['source_kind'] == 'SYNTHETIC_FIXTURE'
    assert result['status'] == 'OK' and len(result['estimates']) == 11
    me = db.scalar(select(User).where(User.login_name == 'demo.student01'))
    assert {e['object_key'] for e in result['estimates']} == {f'student-{me.id}'}
    assert any(e['status'] == 'NOT_COVERED' for e in result['estimates'])
    assert any(e['by_type'].get('SUBJECTIVE') for e in result['estimates'])
    assert client.get(f'/api/v1/courses/{cid}/my-ability', headers=student).json()['status'] == 'NO_REAL_ANALYSIS'
    assert client.get(f'/api/v1/courses/{cid}/my-ability/demo', headers=teacher).status_code == 403
    assert client.get(f'/api/v1/courses/{cid}/my-ability/demo', headers=student).json() == result


def test_b0_real_waits_for_formal_frozen_input(client, auth, demo):
    teacher = auth('demo.teacher')
    cid = demo[0]['course_id']
    response = client.post(f'/api/v1/analysis/courses/{cid}/student-ability/b0-batches',
                           headers=teacher, json={'request_id': 'b0-real', 'mode': 'REAL_INPUT'})
    assert response.status_code == 201, response.text
    assert response.json()['steps'][0]['status'] == 'WAITING_INPUT'


def test_b0_formal_source_is_frozen_and_never_accepts_mock(db, demo):
    from copy import deepcopy
    from app.analysis.framework.ability_b0_line import synthetic_input, create_batch, project
    from app.analysis.framework.contracts import digest
    from app.analysis.framework import service
    from app.db.models.analytics import AnalysisBatch, AnalysisRun, AnalysisArtifact, AnalysisInputSnapshot
    from app.core.errors import AppError
    import pytest
    cid=int(demo[0]['course_id'])
    teacher=db.scalar(select(User).where(User.login_name=='demo.teacher'))
    student=db.scalar(select(User).where(User.login_name=='demo.student01'))
    # Test DB only: emulate a future formal domain service's frozen contract.
    payload=synthetic_input(db,cid)
    payload['source_kind']='DATABASE'
    source=AnalysisBatch(course_id=cid,created_by=teacher.id,mode='REAL_INPUT',status='COMPLETE',
        request_id='formal-source-test',request_hash='0'*64,seed=1,
        configuration={'schema_version':'analysis-v2'},events={})
    db.add(source);db.flush()
    db.add(AnalysisInputSnapshot(batch_id=source.id,scope='ROOT',payload={'is_mock':False},
        input_hash=digest({'is_mock':False}),is_mock=False))
    run=AnalysisRun(batch_id=source.id,step_key='result_snapshot',status='SUCCEEDED',business_status='OK',
                    dependencies=[],implementation_version='1')
    db.add(run);db.flush()
    output={'payload':{'ability_input_v2':payload}}
    artifact=AnalysisArtifact(run_id=run.id,attempt_no=0,output_hash=digest(output),payload=output,is_mock=False)
    db.add(artifact);db.commit()
    body=dict(mode='REAL_INPUT',seed=1,source_batch_id=str(source.id),request_id='formal-b0-test')
    batch=create_batch(db,cid,teacher,body)
    frozen=service.ability_input_view(db,int(batch['id']),teacher)
    assert frozen['algorithm_key']=='ability_b0'
    assert frozen['parameters']['merge_policy']=='CHAPTER_WEIGHT'
    altered=deepcopy(output);altered['payload']['ability_input_v2']['grades'][0]['normalized_score']='0.01'
    artifact.payload=altered;db.commit()
    for _ in range(20):
        if not process_one(db):break
    assert service.ability_input_view(db,int(batch['id']),teacher)['payload']==frozen['payload']
    assert project(db,cid,student)['status']=='OK'
    artifact.is_mock=True;artifact.output_hash=digest(altered);db.commit()
    with pytest.raises(AppError) as error:
        create_batch(db,cid,teacher,dict(body,request_id='mock-rejection'))
    assert error.value.code=='MOCK_SOURCE_NOT_ALLOWED'


def test_b0_no_assigned_student_is_still_in_scope_and_wait_is_truthful(client,auth,demo,db):
    teacher=auth('demo.teacher');student=auth('demo.student06');cid=demo[0]['course_id']
    url=f'/api/v1/analysis/courses/{cid}/student-ability/b0-batches'
    batch=client.post(url,headers=teacher,json={'request_id':'empty-pairs'}).json()
    for _ in range(20):
        if not process_one(db):break
    view=client.get(f'/api/v1/courses/{cid}/my-ability/demo',headers=student).json()
    assert len(view['estimates'])==11 and all(e['status']=='NOT_COVERED' for e in view['estimates'])
    client.post(url,headers=teacher,json={'request_id':'wait-real','mode':'REAL_INPUT'})
    waiting=client.get(f'/api/v1/courses/{cid}/my-ability',headers=student).json()
    assert waiting['status']=='NO_REAL_ANALYSIS' and waiting['reason']=='QUESTION_RESULTS_REQUIRED'
