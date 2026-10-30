"""Short-lived single-worker steps, fenced by per-attempt tokens and leases."""
from datetime import timedelta
import secrets
from sqlalchemy import select
from app.db.base import utcnow
from app.db.models.analytics import AnalysisRun,AnalysisBatch,AnalysisInputSnapshot
from .catalog import invoke,PLUGINS
from .payloads import rule_output
from .service import root_snapshot,refresh,save_output
from .contracts import digest


def recover_expired(db):
    now=utcnow();count=0
    for run in db.scalars(select(AnalysisRun).where(AnalysisRun.status=='RUNNING',AnalysisRun.lease_expires_at<=now)
                          .with_for_update(skip_locked=True)):
        run.status='FAILED';run.attempt_token=None;run.lease_expires_at=None;run.finished_at=now
        run.reason={'reason':'LEASE_EXPIRED_EXPLICIT_RETRY_REQUIRED'}
        run.attempt_history=[*run.attempt_history,dict(attempt_no=run.attempt_no,status='EXPIRED',at=now.isoformat())]
        count+=1
    db.commit();return count


def claim(db):
    run=db.scalar(select(AnalysisRun).join(AnalysisBatch).where(AnalysisRun.status=='READY', AnalysisBatch.status=='ACTIVE', AnalysisBatch.configuration['schema_version'].astext=='analysis-v2').order_by(AnalysisRun.id)
        .with_for_update(skip_locked=True).limit(1))
    if run is None:db.commit();return None
    batch=db.get(AnalysisBatch,run.batch_id);snapshot=db.get(AnalysisInputSnapshot,run.snapshot_id)
    run.status='RUNNING';run.attempt_no+=1;run.attempt_token=secrets.token_hex(24)
    run.started_at=utcnow();run.lease_expires_at=run.started_at+timedelta(seconds=120)
    run.attempt_history=[*run.attempt_history,dict(attempt_no=run.attempt_no,status='STARTED',at=run.started_at.isoformat())]
    ticket=dict(run_id=str(run.id),batch_id=str(batch.id),token=run.attempt_token,algorithm=run.algorithm_key,
        step=run.step_key,payload=snapshot.payload,input_hash=snapshot.input_hash,is_mock=snapshot.is_mock,
        mode=batch.mode,seed=batch.seed,implementation=run.implementation_name,implementation_version=run.implementation_version,
        root=(root_snapshot(db,batch).payload if root_snapshot(db,batch) is not None else {}))
    db.commit();return ticket


def finish(db,ticket,output=None,error=False):
    batch=db.scalar(select(AnalysisBatch).where(AnalysisBatch.id==int(ticket['batch_id'])).with_for_update())
    run=db.scalar(select(AnalysisRun).where(AnalysisRun.id==int(ticket['run_id'])).with_for_update().execution_options(populate_existing=True))
    now=utcnow()
    if run is None or run.status!='RUNNING' or run.attempt_token!=ticket['token'] or run.lease_expires_at<=now:
        db.rollback();return False
    if error:
        run.status='FAILED';run.reason={'reason':error if isinstance(error,str) else 'ALGORITHM_EXECUTION_FAILED','retryable':run.attempt_no<3}
        run.finished_at=now
    else:
        output=dict(output,is_mock=bool(ticket['is_mock'] or output.get('is_mock')))
        save_output(db,run,output,output['is_mock'])
    run.attempt_history=[*run.attempt_history,dict(attempt_no=run.attempt_no,status=run.status,at=now.isoformat())]
    run.attempt_token=None;run.lease_expires_at=None
    refresh(db,batch);db.commit();return True


def process_one(db):
    recover_expired(db)
    ticket=claim(db)
    if ticket is None:return False
    try:
        if ticket['algorithm']:
            plugin=PLUGINS[ticket['algorithm']]
            if plugin.implementation!=ticket['implementation'] or plugin.version!=ticket['implementation_version']:
                finish(db,ticket,error='IMPLEMENTATION_CHANGED_CREATE_NEW_BATCH');return True
            result=invoke(ticket['algorithm'],ticket['payload'],mode=ticket['mode'],seed=ticket['seed'],
                input_hash=ticket['input_hash']).model_dump(mode='json')
        else:
            if digest(ticket['payload'])!=ticket['input_hash']:raise ValueError('Input changed')
            result=dict(schema_version='analysis-v2',algorithm_key=ticket['step'],implementation_name=ticket['implementation'],
                implementation_version=ticket['implementation_version'],input_hash=ticket['input_hash'],is_mock=ticket['is_mock'],status='OK',
                payload=rule_output(ticket['step'],ticket['payload'],ticket['root']),evidence=[],limitations=[])
        finish(db,ticket,result)
    except Exception:
        db.rollback();finish(db,ticket,error=True)
    return True
