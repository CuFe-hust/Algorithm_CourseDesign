"""Real PostgreSQL domain flows: frozen data, human gates and immutable versions."""
from datetime import timedelta
from decimal import Decimal
from uuid import uuid4
import pytest
from sqlalchemy import select,func
from app.db.base import utcnow
from app.db.models import User,Assignment,AssignmentItem,Submission,ReviewRound,ReviewTask,ReviewEvaluation,ReviewAnalysis,ReviewDecision,CourseMember
from app.core.errors import AppError
from app.peer_review import rounds,evaluations,analyses,queries,schemas as s
from app.analysis.framework.runner import process_one


def drain(db):
    db.commit()
    for _ in range(100):
        if not process_one(db):return
    raise AssertionError('worker failed to settle')

@pytest.fixture
def scope(db,demo):
    teacher=db.scalar(select(User).where(User.login_name=='demo.teacher'))
    students=list(db.scalars(select(User).where(User.login_name.like('demo.student%')).order_by(User.id)))
    item=db.scalar(select(AssignmentItem).where(AssignmentItem.rubric_id.is_not(None)).order_by(AssignmentItem.id))
    a=db.get(Assignment,item.assignment_id);a.published_at=utcnow()-timedelta(days=3);a.submission_deadline=utcnow()-timedelta(days=1);a.submission_status='CLOSED';item.required_reviewers=3
    for u in students:
        db.add(Submission(assignment_item_id=item.id,student_id=u.id,version_no=1,content='合成作品：递归式 T(n)=2T(n/2)+n，逐层展开得 Θ(n log n)。',submitted_at=utcnow()-timedelta(days=2),client_request_id=uuid4().hex))
    db.commit();return teacher,students,item


def preview(db,scope,**kwargs):
    teacher,students,item=scope
    result=rounds.create_preview(db,item.id,teacher,s.Preview(request_id=uuid4().hex,review_deadline=utcnow()+timedelta(days=2),**kwargs))
    drain(db);return db.get(ReviewRound,int(result['id']))


def publish(db,scope,r):
    rounds.publish(db,r.id,scope[0],s.Publish(request_id=uuid4().hex,expected_revision=r.revision_no,expected_source_hash=r.source_hash));db.commit()


def score_all(db,scope,r):
    students={u.id:u for u in scope[1]}
    tasks=list(db.scalars(select(ReviewTask).where(ReviewTask.round_id==r.id).order_by(ReviewTask.id)))
    for t in tasks:
        view=evaluations.open_task(db,t.id,students[t.reviewer_id]);db.commit()
        body=s.EvaluationInput(client_request_id=uuid4().hex,comment='递推展开过程正确，建议补充边界条件。',scores=[dict(rubric_item_id=d['id'],score=str(Decimal(d['max_score'])*Decimal('.8'))) for d in view['rubric']])
        evaluations.submit(db,t.id,students[t.reviewer_id],body);db.commit()
    return tasks


def close(db,scope,r,accept=False):
    result=rounds.close(db,r.id,scope[0],s.Close(request_id=uuid4().hex,expected_revision=r.revision_no,reason='合成流程封存',accept_incomplete=accept));drain(db)
    return analyses.latest(db,db.get(ReviewRound,int(result['root_round_id'])))


def resolve(db,scope,root,a,decisions=(),supplement=False):
    statuses={run['key']:run['business_status'] for run in queries.analysis_view(db,a)['runs'] if run['key'] in ('deviation','reviewer_bias','review_timing','relationship')}
    result=analyses.resolve(db,a.id,scope[0],s.Resolve(request_id=uuid4().hex,expected_revision=root.revision_no,expected_source_hash=a.source_hash,
        acknowledged_statuses=statuses,reason='逐条核对证据；不足部分保留人工判断',decisions=list(decisions),request_supplement=supplement,
        supplement_deadline=utcnow()+timedelta(days=3) if supplement else None));drain(db);return result


def test_full_real_chain_preserves_raw_and_versions(db,scope):
    r=preview(db,scope);assert queries.round_view(db,r.id)['allocation']['business_status']=='OK'
    publish(db,scope,r);tasks=score_all(db,scope,r);a=close(db,scope,r)
    raw=[(e.id,e.total_score,e.comment) for e in db.scalars(select(ReviewEvaluation).order_by(ReviewEvaluation.id))]
    assert len(raw)==18
    statuses={x['key']:x['business_status'] for x in queries.analysis_view(db,a)['runs']}
    assert statuses['reviewer_bias']=='INSUFFICIENT_DATA'
    assert statuses['deviation']=='OK'
    assert analyses.handoff(db,r)['status']=='WAITING_INPUT'
    resolve(db,scope,r,a,[dict(action='DOWNWEIGHT',evaluation_id=raw[0][0],weight='0.5',reason='复核后降低此评价影响')])
    result=analyses.handoff(db,r)
    assert result['status']=='READY' and result['version']==2 and not result['is_mock']
    assert len(result['rows'])==6 and all(Decimal(x['normalized_score'])==Decimal('.8') for x in result['rows'])
    assert [(e.id,e.total_score,e.comment) for e in db.scalars(select(ReviewEvaluation).order_by(ReviewEvaluation.id))]==raw
    assert db.scalar(select(func.count()).select_from(ReviewAnalysis))==2
    assert analyses.material(db,r)['evaluations'][0]['weight']=='0.500000'


def test_supplement_excludes_all_old_pairs_and_overrides_are_question_points(db,scope):
    r=preview(db,scope);publish(db,scope,r);score_all(db,scope,r);a=close(db,scope,r)
    e=db.scalar(select(ReviewEvaluation).order_by(ReviewEvaluation.id));t=db.get(ReviewTask,e.task_id)
    old={(x.answer_key,x.reviewer_id) for x in db.scalars(select(ReviewTask))}
    resolve(db,scope,r,a,[dict(action='INVALIDATE',evaluation_id=e.id,reason='评分依据与量表不符')],True)
    child=db.scalar(select(ReviewRound).where(ReviewRound.root_round_id==r.id));assert child.status=='PREVIEW'
    publish(db,scope,child)
    extra=list(db.scalars(select(ReviewTask).where(ReviewTask.round_id==child.id)))
    assert len(extra)==1 and not old&{(x.answer_key,x.reviewer_id) for x in extra}
    score_all(db,scope,child);a2=close(db,scope,child)
    resolve(db,scope,r,a2,[dict(action='OVERRIDE',answer_key=t.answer_key,override_score='15.25',reason='教师独立重新核对推导')])
    result=analyses.handoff(db,r);row=next(x for x in result['rows'] if x['answer_key']==t.answer_key)
    assert row['item_score']=='15.25' and row['source_type']=='TEACHER_OVERRIDE'
    assert result['version']==3  # initial v1 -> supplemented initial v2 -> recompute v3
    assert db.get(ReviewEvaluation,e.id).total_score==e.total_score


def test_anonymity_ownership_bounds_idempotency_and_server_clock(db,scope):
    r=preview(db,scope);publish(db,scope,r)
    t=db.scalar(select(ReviewTask).order_by(ReviewTask.id));u=db.get(User,t.reviewer_id)
    outsider=next(x for x in scope[1] if x.id!=u.id)
    with pytest.raises(AppError) as err:evaluations.open_task(db,t.id,outsider)
    assert err.value.status==404;db.rollback()
    view=evaluations.open_task(db,t.id,u);db.commit()
    assert all(k not in str(view) for k in ('student_id','reviewer_id','author_key','submission_id','password','reference_solution'))
    body=s.EvaluationInput(client_request_id='stable',scores=[dict(rubric_item_id=d['id'],score=d['max_score']) for d in view['rubric']],comment='完整说明了每个推导步骤。')
    result=evaluations.submit(db,t.id,u,body);db.commit()
    assert result['evaluation']['elapsed_seconds'] is not None
    replay=evaluations.submit(db,t.id,u,body);db.commit();assert replay['replayed']
    with pytest.raises(AppError) as err:evaluations.submit(db,t.id,u,body.model_copy(update={'comment':'不同内容'}))
    assert err.value.code=='IDEMPOTENCY_CONFLICT';db.rollback()
    other=db.scalar(select(ReviewTask).where(ReviewTask.reviewer_id==u.id,ReviewTask.id!=t.id));other_view=evaluations.open_task(db,other.id,u);db.commit()
    bad=s.EvaluationInput(client_request_id='bad',scores=[dict(rubric_item_id=d['id'],score=str(Decimal(d['max_score'])+1)) for d in other_view['rubric']],comment='超界测试')
    with pytest.raises(AppError) as err:evaluations.submit(db,other.id,u,bad)
    assert err.value.code=='SCORE_OUT_OF_RANGE';db.rollback()
    close(db,scope,r,True)
    with pytest.raises(AppError) as err:evaluations.submit(db,other.id,u,bad.model_copy(update={'client_request_id':'late'}))
    assert err.value.code=='REVIEW_CLOSED'


def test_stale_preview_rejects_membership_changes_without_partial_tasks(db,scope):
    r=preview(db,scope);member=db.scalar(select(CourseMember).where(CourseMember.user_id==scope[1][0].id));member.status='REMOVED';db.commit()
    with pytest.raises(AppError) as err:publish(db,scope,r)
    assert err.value.code=='REVIEW_SOURCE_CHANGED';db.rollback()
    assert not db.scalar(select(ReviewTask.id).limit(1))


def test_missing_evaluations_and_no_submission_are_never_zero(db,scope):
    student=scope[1][-1];db.query(Submission).filter(Submission.student_id==student.id).delete();db.commit()
    r=preview(db,scope);publish(db,scope,r);a=close(db,scope,r,True);resolve(db,scope,r,a)
    result=analyses.handoff(db,r)
    assert all(x['normalized_score'] is None and x['item_score'] is None for x in result['rows'])
    assert next(x for x in result['rows'] if x['student_id']==str(student.id))['reason']=='NO_SUBMISSION'


def test_http_role_checks_strict_contracts_and_first_read_clock(client,auth,db,scope):
    r=preview(db,scope);publish(db,scope,r)
    task=db.scalar(select(ReviewTask));student=db.get(User,task.reviewer_id)
    headers=auth(student.login_name);teacher_headers=auth('demo.teacher')
    assert client.get(f'/api/v1/peer-review/teacher/rounds/{r.id}',headers=headers).status_code==403
    assert client.get(f'/api/v1/peer-review/tasks/{task.id}',headers=teacher_headers).status_code==404
    assert client.get(f'/api/v1/peer-review/teacher/tasks/{task.id}',headers=teacher_headers).status_code==200
    db.refresh(task);assert task.opened_at is None
    response=client.get(f'/api/v1/peer-review/tasks/{task.id}',headers=headers)
    assert response.status_code==200 and response.headers['cache-control']=='no-store'
    view=response.json();assert view['opened_at']
    bad=client.post(f'/api/v1/peer-review/tasks/{task.id}/evaluation',headers=headers,json={
        'client_request_id':'http-1','scores':[{'rubric_item_id':d['id'],'score':d['max_score']} for d in view['rubric']],
        'comment':'合成测试：边界条件说明完整。','elapsed_seconds':120})
    assert bad.status_code==422
    good=client.post(f'/api/v1/peer-review/tasks/{task.id}/evaluation',headers=headers,json={
        'client_request_id':'http-1','scores':[{'rubric_item_id':d['id'],'score':d['max_score']} for d in view['rubric']],
        'comment':'合成测试：边界条件说明完整。'})
    assert good.status_code==200 and good.json()['evaluation']['total_score']==view['rubric_max']


def test_submit_races_close_without_losing_or_including_late_evaluations(db,scope,live_client,demo):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    r=preview(db,scope);publish(db,scope,r)
    task=db.scalar(select(ReviewTask));student=db.get(User,task.reviewer_id)
    def login(name):
        response=live_client.post('/api/v1/auth/login',json={'login_name':name,'password':demo[1]})
        assert response.status_code==200;return {'Authorization':'Bearer '+response.json()['access_token']}
    sh=login(student.login_name);th=login('demo.teacher')
    view=live_client.get(f'/api/v1/peer-review/tasks/{task.id}',headers=sh).json()
    gate=Barrier(2)
    def submit_request():
        gate.wait();return live_client.post(f'/api/v1/peer-review/tasks/{task.id}/evaluation',headers=sh,json={
            'client_request_id':'racing','scores':[dict(rubric_item_id=d['id'],score=d['max_score']) for d in view['rubric']], 'comment':'合成并发评审'})
    def close_request():
        gate.wait();return live_client.post(f'/api/v1/peer-review/teacher/rounds/{r.id}/close',headers=th,json={
            'request_id':'racing-close','expected_revision':r.revision_no,'reason':'合成并发封存，明确接受缺评','accept_incomplete':True})
    with ThreadPoolExecutor(2) as pool:
        f=pool.submit(submit_request);g=pool.submit(close_request);sr,cr=f.result(timeout=20),g.result(timeout=20)
    assert cr.status_code==200,cr.text
    assert sr.status_code in (200,409),sr.text
    db.expire_all();a=analyses.latest(db,db.get(ReviewRound,r.id))
    from app.db.models.analytics import AnalysisInputSnapshot
    snap=db.scalar(select(AnalysisInputSnapshot).where(AnalysisInputSnapshot.batch_id==a.batch_id,AnalysisInputSnapshot.scope=='ROOT'))
    assert len(snap.payload['aggregation_input']['evaluations'])==(1 if sr.status_code==200 else 0)


def test_decision_validation_ack_and_reanalysis_reset_current_handoff(db,scope):
    r=preview(db,scope);publish(db,scope,r);score_all(db,scope,r);a=close(db,scope,r)
    before=r.revision_no
    with pytest.raises(AppError) as err:
        analyses.resolve(db,a.id,scope[0],s.Resolve(request_id='wrong-ack',expected_revision=before,reason='测试未确认检测',expected_source_hash=a.source_hash,
            acknowledged_statuses={k:'OK' for k in ('deviation','reviewer_bias','review_timing','relationship')}))
    assert err.value.code=='DETECTION_ACK_REQUIRED';db.rollback()
    resolve(db,scope,r,a);assert analyses.handoff(db,r)['status']=='READY'
    analyses.reanalyze(db,r.id,scope[0],s.ReasonCommand(request_id='reanalyze',expected_revision=r.revision_no,reason='显式新建分析版本'))
    db.commit();assert analyses.handoff(db,r)['status']=='WAITING_INPUT'


def test_invalid_override_rolls_back_all_decisions_and_published_schedule_is_frozen(db,scope):
    from app.teacher.assignments import schedule
    from app.teacher.schemas import AssignmentSchedule
    r=preview(db,scope);publish(db,scope,r)
    assignment=db.get(Assignment,scope[2].assignment_id)
    with pytest.raises(AppError) as err:
        schedule(db,assignment.id,scope[0],AssignmentSchedule(expected_updated_at=assignment.updated_at,
            submission_status='OPEN',submission_deadline=utcnow()+timedelta(days=1),review_deadline=utcnow()+timedelta(days=3)))
    assert err.value.code=='REVIEW_SOURCE_FROZEN';db.rollback()
    score_all(db,scope,r);a=close(db,scope,r)
    statuses={run['key']:run['business_status'] for run in queries.analysis_view(db,a)['runs'] if run['key'] in ('deviation','reviewer_bias','review_timing','relationship')}
    e=db.scalar(select(ReviewEvaluation));task=db.get(ReviewTask,e.task_id)
    with pytest.raises(AppError) as err:
        analyses.resolve(db,a.id,scope[0],s.Resolve(request_id='invalid-override',expected_revision=r.revision_no,expected_source_hash=a.source_hash,
            acknowledged_statuses=statuses,reason='合成原子性验证',decisions=[dict(action='INVALIDATE',evaluation_id=e.id,reason='此条本来有效'),
                dict(action='OVERRIDE',answer_key=task.answer_key,override_score=str(scope[2].max_score+1),reason='此分数越界应全部回滚')]))
    assert err.value.code=='OVERRIDE_OUT_OF_RANGE';db.rollback()
    assert db.scalar(select(func.count()).select_from(ReviewDecision))==0
    db.refresh(a);assert a.resolved_at is None


def test_review_candidates_flow_into_shared_question_results_snapshot(db,scope):
    from app.analysis.question_results import create_snapshot
    from app.analysis.integration_router import SnapshotCreate
    r=preview(db,scope);publish(db,scope,r);score_all(db,scope,r);a=close(db,scope,r);resolve(db,scope,r,a)
    report=create_snapshot(db,db.get(Assignment,scope[2].assignment_id).course_id,scope[0],
        SnapshotCreate(request_id='bridge-peer-results',assignment_id=str(scope[2].assignment_id),reason='互评复核到逐题快照的真实接口边界'))
    db.commit();rows=[x for x in report['rows'] if x['normalized_score'] is not None]
    assert len(rows)==6 and all(x['source']['kind']=='REVIEW_ANALYSIS' and x['source']['version']==2 for x in rows)
    assert all(Decimal(x['normalized_score'])==Decimal('.8') for x in rows)
    from app.analysis.course_results import create_snapshot as create_course
    from app.analysis.integration_router import CourseSnapshotCreate
    from app.analysis.framework.ability_b0_line import create_batch,project
    cid=db.get(Assignment,scope[2].assignment_id).course_id
    source=create_course(db,cid,scope[0],CourseSnapshotCreate(request_id='peer-course',reason='复核主观证据接入章节模型'))
    db.commit()
    create_batch(db,cid,scope[0],dict(mode='REAL_INPUT',seed=1,request_id='peer-b0',source_batch_id=source['id']))
    drain(db)
    from app.db.models import User
    student=db.scalar(select(User).where(User.id==int(rows[0]['student_id'])))
    view=project(db,cid,student)
    assert view['status']=='OK' and not view['is_mock']
    assert any('SUBJECTIVE' in e['by_type'] for e in view['estimates'])
