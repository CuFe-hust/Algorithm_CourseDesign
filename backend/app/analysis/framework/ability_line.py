"""Sixth-line input adapters only. The existing ability black box is untouched."""
import json
from sqlalchemy import select
from pydantic import ValidationError
from app.core.config import ROOT
from app.core.errors import AppError
from app.db.models.analytics import AnalysisRun,AnalysisArtifact
from .contracts import LearningInput,digest


def capture_input(db,course_id,actor,mode,source_batch_id):
    from .service import context,root_snapshot
    if source_batch_id is None:
        if mode=='REAL_INPUT':
            return dict(is_mock=False,learning_input=None,source={'kind':'AWAITING_QUESTION_RESULTS'})
        # Reuse the published synthetic input, not a new scoring/ability method.
        sample=json.loads((ROOT/'data/analysis/example-inputs.json').read_text(encoding='utf-8'))['ability']
        data=LearningInput.model_validate(sample['payload']).model_dump(mode='json')
        return dict(is_mock=True,learning_input=data,source={'kind':'SYNTHETIC_EXAMPLE','input_hash':digest(data)})
    source=context(db,int(source_batch_id),actor)
    if source.course_id!=course_id:
        raise AppError(404,'NOT_FOUND','题目结果不属于当前课程')
    if source.status=='CANCELLED':
        raise AppError(409,'QUESTION_RESULTS_REQUIRED','来源批次已取消')
    run=db.scalar(select(AnalysisRun).where(AnalysisRun.batch_id==source.id,
        AnalysisRun.step_key=='result_snapshot',AnalysisRun.status=='SUCCEEDED',AnalysisRun.business_status=='OK'))
    artifact=db.scalar(select(AnalysisArtifact).where(AnalysisArtifact.run_id==run.id)
        .order_by(AnalysisArtifact.attempt_no.desc()).limit(1)) if run else None
    if artifact is None:
        raise AppError(409,'QUESTION_RESULTS_REQUIRED','来源批次尚无已保存的题目结果快照')
    is_mock=artifact.is_mock or root_snapshot(db,source).is_mock or source.mode=='DEMO'
    if mode=='REAL_INPUT' and is_mock:
        raise AppError(409,'MOCK_SOURCE_NOT_ALLOWED','演示题目结果不能作为真实分析输入')
    try:
        if digest(artifact.payload)!=artifact.output_hash:raise ValueError('Source changed')
        payload=artifact.payload['payload']
        data=LearningInput.model_validate(dict(grades=payload['grades'],
            results_snapshot_version=payload['results_snapshot_version'],minimum_samples=2)).model_dump(mode='json')
    except (KeyError,ValueError,ValidationError):
        raise AppError(409,'QUESTION_RESULTS_INVALID','来源快照结构或摘要不一致') from None
    if not data['grades']:
        raise AppError(409,'QUESTION_RESULTS_REQUIRED','题目结果为空')
    return dict(is_mock=bool(is_mock or mode=='DEMO'),learning_input=data,source=dict(
        kind='DATABASE_QUESTION_RESULTS',batch_id=str(source.id),run_id=str(run.id),
        artifact_id=str(artifact.id),output_hash=artifact.output_hash,input_hash=digest(data)))
