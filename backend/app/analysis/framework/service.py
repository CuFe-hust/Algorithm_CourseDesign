"""Transactional batch commands and dependency state transitions."""
from datetime import timezone
from sqlalchemy import select
from app.common.permissions import require_teacher
from app.core.errors import AppError
from app.db.base import utcnow
from app.db.models import User
from app.db.models.analytics import AnalysisBatch,AnalysisRun,AnalysisArtifact,AnalysisInputSnapshot
from .contracts import digest
from .catalog import PLUGINS
from .graph import STEPS,BY_KEY,steps_for
from .snapshots import capture
from .payloads import prepare,human_output,MissingInput,NotApplicable,body

TERMINAL={'SUCCEEDED','SKIPPED'}


def context(db,batch_id,actor,lock=False):
    stmt=select(AnalysisBatch).where(AnalysisBatch.id==batch_id)
    if lock:stmt=stmt.with_for_update().execution_options(populate_existing=True)
    batch=db.scalar(stmt)
    if batch is None:raise AppError(404,'NOT_FOUND','分析批次不存在或不可访问')
    require_teacher(db,batch.course_id,actor.id)
    if batch.configuration.get('schema_version')!='analysis-v2':
        raise AppError(409,'ANALYSIS_BATCH_SCHEMA_OUTDATED','分析批次结构已更新，请新建批次')
    return batch


def records(db,batch):
    runs={r.step_key:r for r in db.scalars(select(AnalysisRun).where(AnalysisRun.batch_id==batch.id).order_by(AnalysisRun.id))}
    artifacts={}
    if runs:
        for a in db.scalars(select(AnalysisArtifact).where(AnalysisArtifact.run_id.in_([r.id for r in runs.values()]))
                           .order_by(AnalysisArtifact.id)):
            artifacts[a.run_id]=a
    return runs,artifacts


def root_snapshot(db,batch):
    return db.scalar(select(AnalysisInputSnapshot).where(AnalysisInputSnapshot.batch_id==batch.id,
        AnalysisInputSnapshot.scope=='ROOT'))


def outputs(runs,artifacts):
    return {k:artifacts[r.id].payload for k,r in runs.items() if r.id in artifacts and r.status in TERMINAL}


def save_output(db,run,output,is_mock):
    db.add(AnalysisArtifact(run_id=run.id,attempt_no=run.attempt_no,output_hash=digest(output),payload=output,is_mock=is_mock))
    run.status='SUCCEEDED';run.business_status=output['status'];run.finished_at=utcnow();run.reason={}
    db.flush()


def refresh(db,batch):
    """Called with the batch lock held. Never runs algorithms or invents human input."""
    root_row=root_snapshot(db,batch)
    runs,artifacts=records(db,batch)
    root=root_row.payload if root_row is not None else {}
    for step in steps_for(batch):
        run=runs[step.key]
        if run.status not in ('WAITING_INPUT','WAITING_HUMAN'):continue
        blocked=[k for k in step.dependencies if runs[k].status not in TERMINAL]
        if blocked:
            run.status='WAITING_INPUT';run.reason={'blocked_by':blocked,
                'upstream_status':{k:runs[k].status for k in blocked},'reason':'DEPENDENCY_NOT_READY'};continue
        out=outputs(runs,artifacts)
        partial_review=(batch.configuration.get('pipeline','').startswith('REVIEW_')
                        and step.key in ('deviation','reviewer_bias','relationship','effective_subjective_results'))
        invalid=[k for k in step.dependencies if runs[k].business_status not in
                 (('OK',None,'INSUFFICIENT_DATA') if partial_review else ('OK',None))
                 and step.key!='resolve']
        if invalid:
            run.status='WAITING_INPUT';run.reason={'blocked_by':invalid,'reason':'UPSTREAM_BUSINESS_RESULT_UNAVAILABLE'};continue
        if step.key=='collect_supplement' and runs['supplement_allocation'].status=='SKIPPED':
            run.status='SKIPPED';run.reason={'reason':'NO_SUPPLEMENT_REQUIRED'};continue
        if step.event:
            run.status='WAITING_HUMAN';run.reason={'event':step.event,'reason':
                'DEMO_EVENT_REQUIRED' if batch.mode=='DEMO' else 'REAL_DOMAIN_EVENT_REQUIRED' if root.get('review_domain') else 'REAL_DOMAIN_SERVICE_NOT_CONNECTED'};continue
        try:payload=prepare(step.key,root,out)
        except NotApplicable as error:
            run.status='SKIPPED';run.reason={'reason':str(error)};continue
        except MissingInput as error:
            run.status='WAITING_INPUT';run.reason={'reason':str(error)};continue
        h=digest(payload)
        snap=db.scalar(select(AnalysisInputSnapshot).where(AnalysisInputSnapshot.batch_id==batch.id,
            AnalysisInputSnapshot.scope==step.key,AnalysisInputSnapshot.input_hash==h))
        inherited_mock=root['is_mock'] or any(artifacts[runs[k].id].is_mock for k in step.dependencies if runs[k].id in artifacts)
        if snap is None:
            snap=AnalysisInputSnapshot(batch_id=batch.id,scope=step.key,input_hash=h,payload=payload,is_mock=inherited_mock)
            db.add(snap);db.flush()
        run.snapshot_id=snap.id
        run.dependency_refs=[dict(step=k,run_id=str(runs[k].id),artifact_id=str(artifacts[runs[k].id].id)
            if runs[k].id in artifacts else None) for k in step.dependencies]
        run.status='READY';run.reason={}
    batch.status='COMPLETE' if all(r.status in TERMINAL for r in runs.values()) else 'ACTIVE'
    db.flush()


def create_batch(db,course_id,actor,body):
    require_teacher(db,course_id,actor.id)
    # Serialise creation for one user so two equal idempotent requests replay cleanly.
    db.scalar(select(User).where(User.id==actor.id).with_for_update())
    h=digest(dict(body,course_id=str(course_id)))
    existing=db.scalar(select(AnalysisBatch).where(AnalysisBatch.created_by==actor.id,
        AnalysisBatch.request_id==body['request_id']))
    if existing:
        if existing.request_hash!=h:raise AppError(409,'IDEMPOTENCY_CONFLICT','同一请求标识不能对应不同分析输入')
        db.commit();return batch_view(db,existing.id,actor)
    data=capture(db,course_id,int(body['assignment_id']) if body.get('assignment_id') else None,
        body['mode'],body['seed'],assignment_item_id=int(body['assignment_item_id']) if body.get('assignment_item_id') else None)
    if len(str(data).encode('utf-8'))>8*1024*1024:
        raise AppError(422,'ANALYSIS_SCOPE_TOO_LARGE','输入快照超过8MiB，请缩小范围')
    batch=AnalysisBatch(course_id=course_id,assignment_id=int(body['assignment_id']) if body.get('assignment_id') else None,
        created_by=actor.id,mode=body['mode'],request_id=body['request_id'],request_hash=h,
        seed=body['seed'],configuration={**{k:v for k,v in body.items() if k!='request_id'},'schema_version':'analysis-v2'},events={})
    db.add(batch);db.flush()
    db.add(AnalysisInputSnapshot(batch_id=batch.id,scope='ROOT',input_hash=digest(data),payload=data,is_mock=data['is_mock']))
    for step in STEPS:
        plugin=PLUGINS[step.algorithm] if step.algorithm else None
        db.add(AnalysisRun(batch_id=batch.id,step_key=step.key,algorithm_key=step.algorithm,dependencies=list(step.dependencies),
            implementation_name=plugin.implementation if plugin else 'synthetic_human_event' if step.event else 'deterministic_rule',
            implementation_version=plugin.version if plugin else '1'))
    db.flush();refresh(db,batch);db.commit()
    return batch_view(db,batch.id,actor)


def batch_view(db,batch_id,actor):
    batch=context(db,batch_id,actor);runs,artifacts=records(db,batch);root=root_snapshot(db,batch)
    # Similarity batches keep one snapshot per item and no ROOT row: comparing
    # submissions of different questions has no meaning, so there is no single
    # course-wide input to hash.
    return dict(id=str(batch.id),course_id=str(batch.course_id),mode=batch.mode,status=batch.status,
        revision_no=batch.revision_no,seed=batch.seed,schema_version='analysis-v2',
        input_hash=root.input_hash if root is not None else None,
        pipeline=batch.configuration.get('pipeline','FULL'),
        is_mock=root.is_mock if root is not None else any(a.is_mock for a in artifacts.values()),
        created_at=batch.created_at.astimezone(timezone.utc).isoformat(),
        steps=[dict(id=str(r.id),key=r.step_key,algorithm=r.algorithm_key,status=r.status,
            business_status=r.business_status,dependencies=r.dependencies,dependency_refs=r.dependency_refs,
            reason=r.reason,attempt_no=r.attempt_no,result=artifacts[r.id].payload if r.id in artifacts and r.status in TERMINAL else None)
            for r in runs.values()])


def _request(batch,actor,request_id,data):
    key=f'{actor.id}:{request_id}';h=digest(data);requests=batch.events.get('_requests',{})
    if key in requests:
        if requests[key]!=h:raise AppError(409,'IDEMPOTENCY_CONFLICT','请求标识已用于其他操作')
        return key,h,True
    if len(requests)>=100:raise AppError(409,'BATCH_COMMAND_LIMIT','批次操作次数已达上限，请创建新批次')
    return key,h,False


def _remember(batch,key,h,extra=None):
    events=dict(batch.events);requests=dict(events.get('_requests',{}));requests[key]=h;events['_requests']=requests
    if extra:events.update(extra)
    batch.events=events


def advance(db,batch_id,actor,request_id):
    batch=context(db,batch_id,actor,True)
    key,h,replay=_request(batch,actor,request_id,{'operation':'run'})
    if not replay:_remember(batch,key,h);refresh(db,batch)
    db.commit();return batch_view(db,batch_id,actor)


def demo_event(db,batch_id,actor,body):
    batch=context(db,batch_id,actor,True)
    if batch.mode!='DEMO':raise AppError(409,'DEMO_ONLY','真实输入模式不能提交合成事件')
    key,h,replay=_request(batch,actor,body['request_id'],dict(body,operation='demo_event'))
    if replay:db.commit();return batch_view(db,batch_id,actor)
    if batch.revision_no!=body['expected_version']:
        raise AppError(409,'VERSION_CONFLICT','批次已变化，请重新读取')
    step=next((s for s in steps_for(batch) if s.event==body['event']),None)
    if step is None:raise AppError(422,'INVALID_DEMO_EVENT','未知演示事件')
    run=db.scalar(select(AnalysisRun).where(AnalysisRun.batch_id==batch.id,AnalysisRun.step_key==step.key).with_for_update())
    if run.status!='WAITING_HUMAN':raise AppError(409,'EVENT_NOT_READY','当前步骤尚未等待此事件')
    root=root_snapshot(db,batch).payload;runs,artifacts=records(db,batch)
    payload=human_output(step.key,root,outputs(runs,artifacts),body.get('action','KEEP'))
    output=dict(schema_version='analysis-v2',algorithm_key=step.key,implementation_name='synthetic_human_event',
        implementation_version='1',input_hash=digest(dict(root_hash=digest(root),event=body)),
        is_mock=True,status='OK',payload=payload,evidence=[],limitations=['Synthetic event, not a real domain action.'])
    save_output(db,run,output,True)
    _remember(batch,key,h,{body['event']:dict(request_id=body['request_id'],revision=batch.revision_no+1)})
    batch.revision_no+=1;refresh(db,batch);db.commit();return batch_view(db,batch_id,actor)


def retry_run(db,batch_id,run_id,actor,request_id):
    batch=context(db,batch_id,actor,True)
    key,h,replay=_request(batch,actor,request_id,{'operation':'retry','run_id':str(run_id)})
    if not replay:
        run=db.scalar(select(AnalysisRun).where(AnalysisRun.id==run_id,AnalysisRun.batch_id==batch_id).with_for_update())
        if run is None:raise AppError(404,'NOT_FOUND','任务不可访问')
        if run.status!='FAILED' or run.attempt_no>=3:
            raise AppError(409,'RETRY_NOT_ALLOWED','任务不允许重试或已用尽3次尝试')
        run.status='READY';run.reason={};run.attempt_token=None;run.lease_expires_at=None
        _remember(batch,key,h)
    db.commit();return batch_view(db,batch_id,actor)


def create_ability_batch(db,course_id,actor,body):
    from .ability_line import capture_input
    require_teacher(db,course_id,actor.id)
    db.scalar(select(User).where(User.id==actor.id).with_for_update())
    h=digest(dict(body,course_id=str(course_id),pipeline='STUDENT_ABILITY'))
    existing=db.scalar(select(AnalysisBatch).where(AnalysisBatch.created_by==actor.id,
        AnalysisBatch.request_id==body['request_id']))
    if existing:
        if existing.request_hash!=h:raise AppError(409,'IDEMPOTENCY_CONFLICT','同一请求标识不能对应不同分析输入')
        db.commit();return batch_view(db,existing.id,actor)
    data=capture_input(db,course_id,actor,body['mode'],body.get('source_batch_id'))
    if len(str(data).encode('utf-8'))>8*1024*1024:
        raise AppError(422,'ANALYSIS_SCOPE_TOO_LARGE','输入快照超过8MiB，请缩小范围')
    batch=AnalysisBatch(course_id=course_id,created_by=actor.id,mode=body['mode'],request_id=body['request_id'],
        request_hash=h,seed=body['seed'],configuration=dict(schema_version='analysis-v2',pipeline='STUDENT_ABILITY',
        source_batch_id=body.get('source_batch_id')),events={})
    db.add(batch);db.flush()
    db.add(AnalysisInputSnapshot(batch_id=batch.id,scope='ROOT',input_hash=digest(data),payload=data,is_mock=data['is_mock']))
    plugin=PLUGINS['ability']
    db.add(AnalysisRun(batch_id=batch.id,step_key='ability',algorithm_key='ability',dependencies=[],
        implementation_name=plugin.implementation,implementation_version=plugin.version))
    db.flush();refresh(db,batch);db.commit()
    return batch_view(db,batch.id,actor)


def ability_input_view(db,batch_id,actor):
    batch=context(db,batch_id,actor)
    if batch.configuration.get('pipeline') not in ('STUDENT_ABILITY','STUDENT_ABILITY_B0','STUDENT_ABILITY_D1'):
        raise AppError(404,'NOT_FOUND','此入口仅用于第六条独立线路')
    snap=root_snapshot(db,batch)
    run=db.scalar(select(AnalysisRun).where(AnalysisRun.batch_id==batch.id,AnalysisRun.step_key=='ability'))
    algorithm_input=db.get(AnalysisInputSnapshot,run.snapshot_id) if run.snapshot_id else None
    return dict(batch_id=str(batch.id),schema_version='analysis-v2',algorithm_key=run.algorithm_key,seed=batch.seed,
        parameters=(algorithm_input.payload.get('model_parameters',algorithm_input.payload.get('parameters',{})) if algorithm_input else {}),
        snapshot_id=str(algorithm_input.id) if algorithm_input else None,
        input_hash=algorithm_input.input_hash if algorithm_input else None,is_mock=snap.is_mock,
        source_snapshot_id=str(snap.id),source_hash=snap.input_hash,
        source=snap.payload['source'],payload=snap.payload['learning_input'])
