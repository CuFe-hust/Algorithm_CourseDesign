from sqlalchemy import select
from app.db.models import User
from app.analysis.framework.runner import process_one
from app.analysis.framework.contracts import digest


def test_difficulty_demo_persists_model_and_baseline_with_self_only_projection(client,auth,demo,db):
    teacher=auth('demo.teacher');student=auth();cid=demo[0]['course_id']
    path=f'/api/v1/analysis/courses/{cid}/student-ability/difficulty-batches'
    assert client.post(path,headers=student,json={'request_id':'deny-d1'}).status_code==403
    result=client.post(path,headers=teacher,json={'request_id':'d1-flow'})
    assert result.status_code==201,result.text
    batch=result.json();bid=batch['id']
    frozen=client.get(f'/api/v1/analysis/batches/{bid}/input',headers=teacher).json()
    assert frozen['algorithm_key']=='ability_d1'
    assert frozen['input_hash']==digest(frozen['payload'])
    assert frozen['payload']['model_parameters']['learner_l2']>0
    for _ in range(30):
        if not process_one(db):break
    complete=client.get(f'/api/v1/analysis/batches/{bid}',headers=teacher).json()
    assert complete['status']=='COMPLETE',complete
    artifact=complete['steps'][0]['result']
    assert artifact['implementation_name']=='difficulty_fractional'
    assert artifact['is_mock'] and artifact['input_hash']==frozen['input_hash']
    view=client.get(f'/api/v1/courses/{cid}/my-ability/difficulty/demo',headers=student)
    assert view.status_code==200,view.text
    report=view.json()
    assert report['status']=='OK' and len(report['estimates'])==11
    me=db.scalar(select(User).where(User.login_name=='demo.student01'))
    assert {e['object_key'] for e in report['estimates']}=={f'student-{me.id}'}
    assert all(e['value'] is None for e in report['estimates'] if e['status'] in ('NO_EVIDENCE','NOT_COVERED'))
    assert any(e['baseline_value']!=e['value'] for e in report['estimates'] if e['value'] is not None)
    assert report['model_diagnostics']['score_semantics']=='REFERENCE_EXPECTED_SCORE'
    assert report['process_diagnostics']['available']
    assert client.get(f'/api/v1/courses/{cid}/my-ability/difficulty',headers=student).json()['status']=='NO_REAL_ANALYSIS'
    assert client.get(f'/api/v1/courses/{cid}/my-ability/difficulty/demo',headers=teacher).status_code==403
    assert client.get(f'/api/v1/courses/{cid}/my-ability/difficulty/demo',headers=student).json()==report


def test_difficulty_real_without_source_waits_and_legacy_b0_stays_available(client,auth,demo):
    teacher=auth('demo.teacher');student=auth();cid=demo[0]['course_id']
    result=client.post(f'/api/v1/analysis/courses/{cid}/student-ability/difficulty-batches',headers=teacher,
                       json={'request_id':'d1-wait','mode':'REAL_INPUT'})
    assert result.status_code==201,result.text
    assert result.json()['steps'][0]['status']=='WAITING_INPUT'
    assert client.get(f'/api/v1/courses/{cid}/my-ability/difficulty',headers=student).json()['status']=='NO_REAL_ANALYSIS'
    assert client.get(f'/api/v1/courses/{cid}/my-ability/demo',headers=student).json()['status']=='NO_DEMO_ANALYSIS'
