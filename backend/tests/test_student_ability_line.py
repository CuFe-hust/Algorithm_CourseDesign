import pytest
from sqlalchemy import select
from app.db.models import User
from app.core.errors import AppError
from app.analysis.framework import service
from app.analysis.framework.runner import process_one


def actor(db):return db.scalar(select(User).where(User.login_name=='demo.teacher'))


def run(db):
    for _ in range(100):
        if not process_one(db):return
    raise AssertionError('did not settle')


def test_sixth_line_runs_alone_with_unchanged_ability_black_box(db,demo):
    cid=int(demo[0]['course_id'])
    body=dict(mode='DEMO',seed=42,source_batch_id=None,request_id='ability-only')
    view=service.create_ability_batch(db,cid,actor(db),body)
    bid=int(view['id'])
    assert view['pipeline']=='STUDENT_ABILITY'
    assert [(s['key'],s['status']) for s in view['steps']]==[('ability','READY')]
    source=service.ability_input_view(db,bid,actor(db))
    assert len(source['payload']['grades'])==12 and source['is_mock']
    from app.analysis.framework.contracts import digest
    assert source['input_hash']==digest(source['payload'])
    run(db)
    complete=service.batch_view(db,bid,actor(db))
    assert complete['status']=='COMPLETE' and complete['steps'][0]['result']['is_mock']
    assert complete['steps'][0]['result']['implementation_name']=='synthetic_demo'
    assert complete['steps'][0]['result']['payload']['estimates']
    assert service.create_ability_batch(db,cid,actor(db),body)['id']==str(bid)


def test_real_sixth_line_without_upstream_results_waits_instead_of_faking(db,demo):
    view=service.create_ability_batch(db,int(demo[0]['course_id']),actor(db),dict(
        mode='REAL_INPUT',seed=42,source_batch_id=None,request_id='real-ability'))
    assert view['steps'][0]['status']=='WAITING_INPUT'
    assert view['steps'][0]['reason']['reason']=='QUESTION_RESULTS_REQUIRED'
    student=db.scalar(select(User).where(User.login_name=='demo.student01'))
    with pytest.raises(AppError):service.ability_input_view(db,int(view['id']),student)


def test_ability_line_http_is_teacher_only_and_has_no_human_gates(client,auth,demo,db):
    teacher=auth('demo.teacher');student=auth();cid=demo[0]['course_id']
    path=f'/api/v1/analysis/courses/{cid}/student-ability/batches'
    response=client.post(path,headers=teacher,json={'request_id':'http-ability'})
    assert response.status_code==201,response.text
    bid=response.json()['id']
    assert client.get(f'/api/v1/analysis/batches/{bid}/input',headers=teacher).status_code==200
    assert client.get(f'/api/v1/analysis/batches/{bid}/input',headers=student).status_code==403
    assert client.post(path,headers=student,json={'request_id':'student-denied'}).status_code==403
    response=client.post(f'/api/v1/analysis/batches/{bid}/demo-events',headers=teacher,
        json={'event':'OPEN_REVIEW','request_id':'irrelevant','expected_version':0})
    assert response.status_code==422


def full_source(db,demo):
    from test_analysis_flow import create,event,drain
    bid=int(create(db,demo)['id']);drain(db)
    for name in ('OPEN_REVIEW','SUBMIT_REVIEWS','RESOLVE'):
        event(db,bid,name);drain(db)
    return bid


def test_saved_question_results_are_copied_without_rerunning_other_lines(db,demo):
    from copy import deepcopy
    from app.db.models.analytics import AnalysisRun,AnalysisArtifact
    source=full_source(db,demo);cid=int(demo[0]['course_id'])
    batch=service.create_ability_batch(db,cid,actor(db),dict(mode='DEMO',seed=42,
        source_batch_id=str(source),request_id='source-copy'))
    bid=int(batch['id']);before=service.ability_input_view(db,bid,actor(db))
    assert before['source']['kind']=='DATABASE_QUESTION_RESULTS'
    assert len(before['payload']['grades'])==12 and len(batch['steps'])==1
    artifact=db.get(AnalysisArtifact,int(before['source']['artifact_id']))
    altered=deepcopy(artifact.payload);altered['payload']['grades'][0]['normalized_score']='0.01'
    artifact.payload=altered;db.commit()
    # Destination input was copied/frozen; later source changes cannot alter it.
    run(db)
    assert service.ability_input_view(db,bid,actor(db))['payload']==before['payload']
    assert service.batch_view(db,bid,actor(db))['status']=='COMPLETE'


def test_real_mode_rejects_mock_source_and_cross_course_source(db,demo):
    from app.db.models import Course,CourseMember
    source=full_source(db,demo);teacher=actor(db);cid=int(demo[0]['course_id'])
    body=dict(mode='REAL_INPUT',seed=42,source_batch_id=str(source),request_id='mock-for-real')
    with pytest.raises(AppError) as error:service.create_ability_batch(db,cid,teacher,body)
    assert error.value.code=='MOCK_SOURCE_NOT_ALLOWED';db.rollback()
    other=Course(code='ABILITY_OTHER',name='Synthetic other course',term='2026',created_by=teacher.id)
    db.add(other);db.flush();db.add(CourseMember(course_id=other.id,user_id=teacher.id,role='TEACHER'));db.commit()
    with pytest.raises(AppError) as error:
        service.create_ability_batch(db,other.id,teacher,dict(body,mode='DEMO',request_id='cross-course'))
    assert error.value.status==404;db.rollback()
