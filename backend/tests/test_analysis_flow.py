from datetime import timedelta
import pytest
from sqlalchemy import select
from app.db.base import utcnow
from app.db.models import User
from app.db.models.analytics import AnalysisBatch,AnalysisRun
from app.analysis.framework.service import create_batch,advance,batch_view,demo_event,retry_run
from app.analysis.framework.runner import process_one,claim,finish
from app.analysis.framework.contracts import digest
from app.core.errors import AppError


def teacher(db):return db.scalar(select(User).where(User.login_name=='demo.teacher'))


def drain(db):
    for _ in range(100):
        if not process_one(db):return
    raise AssertionError('Worker did not settle')


def create(db,demo,mode='DEMO'):
    return create_batch(db,int(demo[0]['course_id']),teacher(db),dict(mode=mode,seed=42,
        assignment_id=None,assignment_item_id=None,request_id='create-1'))


def event(db,batch_id,name,request_id=None,action='KEEP'):
    view=batch_view(db,batch_id,teacher(db))
    return demo_event(db,batch_id,teacher(db),dict(event=name,request_id=request_id or name,
        expected_version=view['revision_no'],action=action))


def test_complete_demo_preserves_human_gates_and_parallel_branches(db,demo):
    created=create(db,demo);bid=int(created['id'])
    initial={s['key']:s for s in created['steps']}
    assert all(initial[k]['status']=='READY' for k in ('allocation','code_similarity','judge_adapter','behavior'))
    assert initial['review_timing']['dependencies']==['collect_reviews']
    drain(db)
    view=batch_view(db,bid,teacher(db));steps={s['key']:s for s in view['steps']}
    assert steps['open_review']['status']=='WAITING_HUMAN'
    assert steps['collect_reviews']['status']=='WAITING_INPUT'
    for name in ('OPEN_REVIEW','SUBMIT_REVIEWS'):
        event(db,bid,name);drain(db)
    steps={s['key']:s for s in batch_view(db,bid,teacher(db))['steps']}
    assert steps['resolve']['status']=='WAITING_HUMAN'
    event(db,bid,'RESOLVE');drain(db)
    assert next(s for s in batch_view(db,bid,teacher(db))['steps'] if s['key']=='release')['status']=='WAITING_HUMAN'
    event(db,bid,'RELEASE');drain(db)
    result=batch_view(db,bid,teacher(db))
    assert result['status']=='COMPLETE'
    assert all(s['status'] in ('SUCCEEDED','SKIPPED') for s in result['steps'])
    assert all(s['result']['is_mock'] for s in result['steps'] if s['result'])
    assert len(next(s for s in result['steps'] if s['key']=='mastery')['result']['payload']['estimates'])>0
    assert create(db,demo)['id']==created['id']
    with pytest.raises(AppError):
        create_batch(db,int(demo[0]['course_id']),teacher(db),dict(mode='DEMO',seed=43,
            assignment_id=None,assignment_item_id=None,request_id='create-1'))
    db.rollback()


def test_real_mode_waits_for_missing_inputs_and_rejects_demo_events(db,demo):
    result=create(db,demo,'REAL_INPUT');bid=int(result['id']);drain(db)
    view=batch_view(db,bid,teacher(db))
    assert view['mode']=='REAL_INPUT' and view['status']=='ACTIVE'
    assert next(s for s in view['steps'] if s['key']=='collect_reviews')['status']=='WAITING_INPUT'
    with pytest.raises(AppError) as error:event(db,bid,'OPEN_REVIEW')
    assert error.value.code=='DEMO_ONLY';db.rollback()
    student=db.scalar(select(User).where(User.login_name=='demo.student01'))
    with pytest.raises(AppError) as error:batch_view(db,bid,student)
    assert error.value.status==403


def test_event_replay_conflict_and_stale_worker_result(db,demo):
    created=create(db,demo);bid=int(created['id'])
    ticket=claim(db)
    assert ticket
    run=db.get(AnalysisRun,int(ticket['run_id']));run.lease_expires_at=utcnow()-timedelta(seconds=1);db.commit()
    assert not finish(db,ticket,{'is_mock':True,'payload':{},'status':'OK'})
    drain(db)
    view=batch_view(db,bid,teacher(db))
    first=demo_event(db,bid,teacher(db),dict(event='OPEN_REVIEW',request_id='event-1',expected_version=view['revision_no'],action='KEEP'))
    replay=demo_event(db,bid,teacher(db),dict(event='OPEN_REVIEW',request_id='event-1',expected_version=view['revision_no'],action='KEEP'))
    assert replay['revision_no']==first['revision_no']
    with pytest.raises(AppError) as error:
        demo_event(db,bid,teacher(db),dict(event='SUBMIT_REVIEWS',request_id='event-1',expected_version=view['revision_no'],action='KEEP'))
    assert error.value.code=='IDEMPOTENCY_CONFLICT';db.rollback()


def test_supplement_chain_reuses_matching_and_retains_original_scores(db,demo):
    bid=int(create(db,demo)['id']);drain(db)
    for name in ('OPEN_REVIEW','SUBMIT_REVIEWS'):
        event(db,bid,name);drain(db)
    event(db,bid,'RESOLVE',action='SUPPLEMENT');drain(db)
    before=batch_view(db,bid,teacher(db));steps={s['key']:s for s in before['steps']}
    assert steps['collect_supplement']['status']=='WAITING_HUMAN'
    original=steps['allocation']['result']['payload']['edges']
    extra=steps['supplement_allocation']['result']['payload']['edges']
    assert not {(e['answer_key'],e['reviewer_key']) for e in original} & {(e['answer_key'],e['reviewer_key']) for e in extra}
    event(db,bid,'SUBMIT_SUPPLEMENT');drain(db)
    steps={s['key']:s for s in batch_view(db,bid,teacher(db))['steps']}
    assert steps['reaggregation']['status']=='SUCCEEDED'
    assert steps['collect_reviews']['result']=={s['key']:s for s in before['steps']}['collect_reviews']['result']


def test_analysis_http_permissions_and_validation(client,auth,demo):
    course_id=demo[0]['course_id'];headers=auth('demo.teacher')
    assert client.get('/api/v1/analysis/catalog').status_code==401
    response=client.get('/api/v1/analysis/catalog',headers=headers)
    assert response.status_code==200 and len(response.json()['items'])==15
    create_url=f'/api/v1/analysis/courses/{course_id}/batches'
    data={'mode':'DEMO','seed':42,'request_id':'http-create'}
    response=client.post(create_url,headers=headers,json=data)
    assert response.status_code==201,response.text
    bid=response.json()['id']
    assert client.post(create_url,headers=auth(),json=data).status_code==403
    assert client.get(f'/api/v1/analysis/batches/{bid}',headers=auth()).status_code==403
    assert client.post(create_url,headers=headers,json=dict(data,request_id='nan',seed=1.5)).status_code==422
    assert client.post(create_url,headers=headers,json=dict(data,raw_scores=[100])).status_code==422
    assert client.post(create_url,headers=headers,json=dict(data,assignment_id='9999999999999999999')).status_code==422
    assert client.post(f'/api/v1/analysis/batches/{bid}/demo-events',headers=headers,
        json={'event':'OPEN_REVIEW','request_id':'too-early','expected_version':0}).status_code==409


def test_concurrent_workers_claim_distinct_runs(db,demo):
    from concurrent.futures import ThreadPoolExecutor
    from sqlalchemy.orm import Session
    create(db,demo)
    engine=db.bind
    def take(_):
        with Session(engine) as session:return claim(session)
    with ThreadPoolExecutor(max_workers=2) as pool:
        tickets=list(pool.map(take,range(2)))
    assert len({t['run_id'] for t in tickets})==2
    assert all(t['token'] for t in tickets)


def test_expired_run_retry_preserves_input_and_rejects_stale_token(db,demo):
    from app.analysis.framework.runner import recover_expired
    bid=int(create(db,demo)['id']);ticket=claim(db);rid=int(ticket['run_id'])
    run=db.get(AnalysisRun,rid);snapshot_id=run.snapshot_id
    run.lease_expires_at=utcnow()-timedelta(seconds=1);db.commit()
    recover_expired(db)
    assert not finish(db,ticket,{'status':'OK','is_mock':True,'payload':{}})
    retry_run(db,bid,rid,teacher(db),'retry-expired')
    drain(db);db.expire_all();run=db.get(AnalysisRun,rid)
    assert run.status=='SUCCEEDED' and run.attempt_no==2 and run.snapshot_id==snapshot_id
    assert {h['status'] for h in run.attempt_history}>={'STARTED','EXPIRED','SUCCEEDED'}


def test_delayed_steps_keep_version_pinned_at_batch_creation(db,demo,monkeypatch):
    from dataclasses import replace
    from app.analysis.framework.catalog import PLUGINS
    bid=int(create(db,demo)['id']);drain(db)
    plugin=PLUGINS['aggregation']
    monkeypatch.setitem(PLUGINS,'aggregation',replace(plugin,version='2'))
    for name in ('OPEN_REVIEW','SUBMIT_REVIEWS'):
        event(db,bid,name);drain(db)
    run=db.scalar(select(AnalysisRun).where(AnalysisRun.batch_id==bid,AnalysisRun.step_key=='aggregation'))
    assert run.implementation_version=='1' and run.status=='FAILED'
    assert run.reason['reason']=='IMPLEMENTATION_CHANGED_CREATE_NEW_BATCH'


def test_batch_view_always_serializes_utc_after_database_reload(db,demo):
    bid=int(create(db,demo)['id']);db.expire_all()
    assert batch_view(db,bid,teacher(db))['created_at'].endswith('+00:00')
