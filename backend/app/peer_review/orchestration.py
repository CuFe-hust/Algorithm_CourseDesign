"""Real-domain use of the existing lease-fenced analysis worker, without nested commits."""
import uuid
from sqlalchemy import select
from app.db.models.analytics import AnalysisBatch,AnalysisRun,AnalysisArtifact,AnalysisInputSnapshot
from app.analysis.framework.contracts import digest
from app.analysis.framework.catalog import PLUGINS
from app.analysis.framework.graph import steps_for
from app.analysis.framework.service import refresh,save_output
from app.core.errors import AppError

DETECTORS=('deviation','reviewer_bias','review_timing','relationship')


def create_batch(db,round_,actor,pipeline,data):
    payload={**data,'is_mock':False,'schema_version':'analysis-v2','review_domain':True}
    batch=AnalysisBatch(course_id=round_.course_id,created_by=actor.id,mode='REAL_INPUT',
        request_id='peer-'+uuid.uuid4().hex,request_hash=digest(payload),seed=round_.policy['seed'],
        configuration={'schema_version':'analysis-v2','pipeline':pipeline,'review_round_id':str(round_.id)},events={})
    db.add(batch);db.flush()
    db.add(AnalysisInputSnapshot(batch_id=batch.id,scope='ROOT',input_hash=digest(payload),payload=payload,is_mock=False))
    for step in steps_for(batch):
        plugin=PLUGINS[step.algorithm] if step.algorithm else None
        db.add(AnalysisRun(batch_id=batch.id,step_key=step.key,algorithm_key=step.algorithm,
            dependencies=list(step.dependencies),implementation_name=plugin.implementation if plugin else
                'peer_review_domain_event' if step.event else 'subjective_result_rule',
            implementation_version=plugin.version if plugin else '1'))
    db.flush();refresh(db,batch)
    return batch


def output(db,batch_id,key):
    run=db.scalar(select(AnalysisRun).where(AnalysisRun.batch_id==batch_id,AnalysisRun.step_key==key))
    artifact=db.scalar(select(AnalysisArtifact).where(AnalysisArtifact.run_id==run.id)
        .order_by(AnalysisArtifact.attempt_no.desc()).limit(1)) if run else None
    if run is None or run.status!='SUCCEEDED' or artifact is None:
        return run,None
    if digest(artifact.payload)!=artifact.output_hash or artifact.is_mock or artifact.payload.get('is_mock'):
        raise AppError(409,'REVIEW_OUTPUT_INVALID','真实互评结果缺失、被修改或含模拟来源')
    return run,artifact


def human_event(db,batch_id,key,payload):
    batch=db.scalar(select(AnalysisBatch).where(AnalysisBatch.id==batch_id).with_for_update())
    run=db.scalar(select(AnalysisRun).where(AnalysisRun.batch_id==batch_id,AnalysisRun.step_key==key).with_for_update())
    if run is None or run.status!='WAITING_HUMAN':
        raise AppError(409,'REVIEW_EVENT_NOT_READY','尚未到达此人工步骤，请等待分析任务完成')
    result={'schema_version':'analysis-v2','algorithm_key':key,'implementation_name':'peer_review_domain_event',
        'implementation_version':'1','input_hash':digest(payload),'is_mock':False,'status':'OK',
        'payload':payload,'evidence':[],'limitations':[]}
    save_output(db,run,result,False);refresh(db,batch)
