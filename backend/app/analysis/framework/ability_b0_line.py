"""Frozen B0 task inputs and self-only projections. No scoring policy is invented here."""
import json
from datetime import timezone
from decimal import Decimal

from sqlalchemy import select
from pydantic import ValidationError

from app.common.permissions import course_role, require_teacher
from app.core.config import ROOT
from app.core.errors import AppError
from app.db.models import User, CourseMember
from app.db.models.analytics import AnalysisBatch, AnalysisRun, AnalysisArtifact, AnalysisInputSnapshot
from .ability_contracts import AbilityInputV2
from .contracts import digest
from .catalog import get_plugin
from . import service


def synthetic_input(db, course_id):
    """Deterministic scored fixture using actual question mappings, never random estimates."""
    mapping = json.loads((ROOT/'data/analysis/question-chapter-mapping.json').read_text(encoding='utf-8'))
    taxonomy = json.loads((ROOT/'data/analysis/chapter-taxonomy.json').read_text(encoding='utf-8'))
    chapters = taxonomy['axes']
    students = list(db.scalars(select(CourseMember.user_id).where(
        CourseMember.course_id == course_id, CourseMember.role == 'STUDENT',
        CourseMember.status == 'ACTIVE').order_by(CourseMember.user_id)))
    if not students:
        raise AppError(422, 'STUDENT_SCOPE_REQUIRED', '课程内暂无可演示的学生')
    if len(students)>2000:
        raise AppError(422, 'ANALYSIS_SCOPE_TOO_LARGE', '请缩小分析范围')
    selected = []
    for chapter in chapters[:6]:
        candidates = [q for q in mapping['questions'] if q['chapter_weights'].get(chapter['code']) == 1]
        selected += [q for q in candidates if q['type'] == 'PROGRAMMING'][:2]
        selected += [q for q in candidates if q['type'] != 'PROGRAMMING'][:1]
    for chapter in chapters[6:8]:
        selected += [q for q in mapping['questions'] if q['chapter_weights'].get(chapter['code']) == 1][:1]
    selected = list({q['code']: q for q in selected}.values())
    items = [dict(item_key='fixture-'+q['code'],item_code=q['code'],item_version='fixture-v1',
        item_type=q['type'],difficulty=3,max_score='100',
        chapter_weights={c:str(w) for c,w in q['chapter_weights'].items()}) for q in selected]
    pairs, grades = [], []
    for si, uid in enumerate(students):
        student = f'student-{uid}'
        # Last demo member intentionally has no assigned pairs: all 11 NOT_COVERED.
        if len(students)>1 and si==len(students)-1:
            continue
        for ii, item in enumerate(items):
            chapter = next(iter(item['chapter_weights']))
            state = 'PENDING' if chapter=='CH07' else 'NOT_SUBMITTED' if chapter=='CH08' else 'SCORED'
            pairs.append(dict(student_key=student,item_key=item['item_key'],state=state))
            if state!='SCORED':continue
            value = Decimal(35+(si*17+ii*11)%61)/100
            if si==0 and chapter=='CH02':value=Decimal(0)
            if si==0 and chapter=='CH03':value=Decimal(1)
            grades.append(dict(student_key=student,item_key=item['item_key'],normalized_score=str(value),
                score_version='synthetic-score-v1',result_ref=f'fixture-{uid}-{ii}',
                score_kind='SYNTHETIC_PROGRAMMING' if item['item_type']=='PROGRAMMING' else 'SYNTHETIC_SUBJECTIVE'))
    payload = dict(source_kind='SYNTHETIC_FIXTURE',results_snapshot_version='fixture-question-results-v1',
        scoring_policy_version='SYNTHETIC_INPUT_ONLY-v1',chapter_taxonomy_version=taxonomy['taxonomy_version'],
        chapter_mapping_version=mapping['mapping_version'],
        scope=dict(scope_kind='COURSE',scope_label='合成演示：课程累计章节表现',
                   student_keys=[f'student-{u}' for u in students],assignment_ids=[],expected_pairs=pairs),
        chapter_taxonomy=[{k:c[k] for k in ('order','code','name')} for c in chapters],items=items,grades=grades)
    return AbilityInputV2.model_validate(payload).model_dump(mode='json')


def capture(db, course_id, actor, mode, source_batch_id=None):
    if mode=='DEMO':
        if source_batch_id is not None:
            raise AppError(422,'DEMO_SOURCE_NOT_SUPPORTED','B0演示使用独立合成快照，无需来源批次')
        data=synthetic_input(db,course_id)
        return dict(is_mock=True,learning_input=data,source=dict(kind='SYNTHETIC_FIXTURE',
            input_hash=digest(data),description='Synthetic scores, deterministic B0; not real student records.'))
    if source_batch_id is None:
        return dict(is_mock=False,learning_input=None,source={'kind':'AWAITING_FORMAL_COURSE_SNAPSHOT'})
    source=service.context(db,int(source_batch_id),actor)
    if source.course_id!=course_id:
        raise AppError(404,'NOT_FOUND','来源不属于当前课程')
    if source.assignment_id is not None or source.configuration.get('assignment_item_id'):
        raise AppError(409,'COURSE_SCOPE_REQUIRED','课程累计面板需要课程范围结果快照')
    if source.mode!='REAL_INPUT' or source.status=='CANCELLED':
        raise AppError(409,'MOCK_SOURCE_NOT_ALLOWED','正式分析不能使用演示或已取消来源')
    run=db.scalar(select(AnalysisRun).where(AnalysisRun.batch_id==source.id,
        AnalysisRun.step_key=='result_snapshot',AnalysisRun.status=='SUCCEEDED',AnalysisRun.business_status=='OK'))
    artifact=db.scalar(select(AnalysisArtifact).where(AnalysisArtifact.run_id==run.id)
                       .order_by(AnalysisArtifact.attempt_no.desc()).limit(1)) if run else None
    if artifact is None:
        raise AppError(409,'QUESTION_RESULTS_REQUIRED','来源尚无正式题目结果快照')
    if artifact.is_mock or service.root_snapshot(db,source).is_mock:
        raise AppError(409,'MOCK_SOURCE_NOT_ALLOWED','正式分析不能使用合成来源')
    if digest(artifact.payload)!=artifact.output_hash:
        raise AppError(409,'QUESTION_RESULTS_INVALID','来源摘要不一致')
    payload=artifact.payload.get('payload',{}).get('ability_input_v2')
    if payload is None:
        # Legacy scores omit roster/pair states/item metadata. Do not reconstruct history from live DB.
        return dict(is_mock=False,learning_input=None,source=dict(kind='FORMAL_B0_INPUT_REQUIRED',batch_id=str(source.id)))
    try:
        data=AbilityInputV2.model_validate(payload).model_dump(mode='json')
    except ValidationError:
        raise AppError(409,'QUESTION_RESULTS_INVALID','正式B0输入契约不完整') from None
    if data['source_kind']!='DATABASE':
        raise AppError(409,'MOCK_SOURCE_NOT_ALLOWED','正式输入必须具有数据库证据来源')
    return dict(is_mock=False,learning_input=data,source=dict(kind='DATABASE',batch_id=str(source.id),
        artifact_id=str(artifact.id),output_hash=artifact.output_hash,input_hash=digest(data)))


def create_batch(db,course_id,actor,body,*,model='b0'):
    if model not in ('b0','d1'):raise ValueError('Unknown model')
    pipeline='STUDENT_ABILITY_D1' if model=='d1' else 'STUDENT_ABILITY_B0'
    require_teacher(db,course_id,actor.id)
    db.scalar(select(User).where(User.id==actor.id).with_for_update())
    h=digest(dict(body,course_id=str(course_id),pipeline=pipeline))
    existing=db.scalar(select(AnalysisBatch).where(AnalysisBatch.created_by==actor.id,
        AnalysisBatch.request_id==body['request_id']))
    if existing:
        if existing.request_hash!=h:raise AppError(409,'IDEMPOTENCY_CONFLICT','同一请求标识不能对应不同输入')
        db.commit();return service.batch_view(db,existing.id,actor)
    data=capture(db,course_id,actor,body['mode'],body.get('source_batch_id'))
    if model=='d1':
        from .difficulty_line import enrich
        data=enrich(data,body['mode'])
    if len(json.dumps(data).encode())>8*1024*1024:
        raise AppError(422,'ANALYSIS_SCOPE_TOO_LARGE','输入超过8MiB，请缩小范围')
    kind='SYNTHETIC_FIXTURE' if data['is_mock'] else 'DATABASE'
    batch=AnalysisBatch(course_id=course_id,created_by=actor.id,mode=body['mode'],
        request_id=body['request_id'],request_hash=h,seed=body['seed'],configuration=dict(
            schema_version='analysis-v2',pipeline=pipeline,scope_kind='COURSE',source_kind=kind),events={})
    db.add(batch);db.flush()
    db.add(AnalysisInputSnapshot(batch_id=batch.id,scope='ROOT',input_hash=digest(data),payload=data,is_mock=data['is_mock']))
    plugin=get_plugin('ability_d1' if model=='d1' else 'ability_b0')
    db.add(AnalysisRun(batch_id=batch.id,step_key='ability',algorithm_key=plugin.key,dependencies=[],
        implementation_name=plugin.implementation,implementation_version=plugin.version))
    db.flush();service.refresh(db,batch);db.commit()
    return service.batch_view(db,batch.id,actor)


def project(db,course_id,actor,demo=False,*,model='b0'):
    if model not in ('b0','d1'):raise ValueError('Unknown model')
    if course_role(db,course_id,actor.id)!='STUDENT':
        raise AppError(403,'STUDENT_REQUIRED','仅可查看本人学生面板')
    kind='SYNTHETIC_FIXTURE' if demo else 'DATABASE'
    response=dict(status='NO_DEMO_ANALYSIS' if demo else 'NO_REAL_ANALYSIS',course_id=str(course_id),
                  is_mock=demo,source_kind=kind,estimates=[])
    batch=db.scalar(select(AnalysisBatch).where(AnalysisBatch.course_id==course_id,
        AnalysisBatch.configuration['pipeline'].astext==('STUDENT_ABILITY_D1' if model=='d1' else 'STUDENT_ABILITY_B0'),
        AnalysisBatch.configuration['scope_kind'].astext=='COURSE',
        AnalysisBatch.configuration['source_kind'].astext==kind,
        AnalysisBatch.status!='CANCELLED').order_by(AnalysisBatch.id.desc()).limit(1))
    if batch is None:return response
    response.update(batch_id=str(batch.id),computed_at=None)
    if batch.status!='COMPLETE':
        pending_run=db.scalar(select(AnalysisRun).where(AnalysisRun.batch_id==batch.id,AnalysisRun.step_key=='ability'))
        if pending_run and pending_run.status=='WAITING_INPUT':
            response['reason']=pending_run.reason.get('reason','QUESTION_RESULTS_REQUIRED')
        else:
            response['status']='ANALYSIS_FAILED' if pending_run and pending_run.status=='FAILED' else 'ANALYSIS_PENDING'
        return response
    run=db.scalar(select(AnalysisRun).where(AnalysisRun.batch_id==batch.id,AnalysisRun.step_key=='ability',
        AnalysisRun.status=='SUCCEEDED'))
    artifact=db.scalar(select(AnalysisArtifact).where(AnalysisArtifact.run_id==run.id)
        .order_by(AnalysisArtifact.attempt_no.desc()).limit(1)) if run else None
    root=service.root_snapshot(db,batch)
    if artifact is None or root is None:return response
    output=artifact.payload
    if bool(root.is_mock)!=demo or bool(artifact.is_mock)!=demo or bool(output.get('is_mock'))!=demo:
        raise AppError(409,'ANALYSIS_PROVENANCE_INVALID','结果来源标记不一致')
    if digest(output)!=artifact.output_hash:
        raise AppError(409,'ANALYSIS_RESULT_INVALID','结果摘要不一致')
    data=output['payload'];student=f'student-{actor.id}'
    if data.get('source_kind')!=kind:
        raise AppError(409,'ANALYSIS_PROVENANCE_INVALID','结果来源类型不一致')
    frozen=root.payload['learning_input']
    scope_input=frozen['learning_input'] if model=='d1' else frozen
    if student not in scope_input['scope']['student_keys']:
        response['status']='NOT_IN_SCOPE';return response
    estimates=[{k:v for k,v in e.items() if k!='evidence_item_keys'} for e in data['estimates'] if e['object_key']==student]
    response.update(status='OK' if any(e['value'] is not None for e in estimates) else 'INSUFFICIENT_DATA',
        computed_at=run.finished_at.astimezone(timezone.utc).isoformat(),estimates=estimates,
        implementation_version=run.implementation_version,
        **{k:data[k] for k in ('results_snapshot_version','scoring_policy_version','chapter_mapping_version',
                              'chapter_taxonomy_version','contract_version')})
    if model=='d1':
        response.update(method=data['method'],model_parameters=data['model_parameters'],
                        model_diagnostics=data['model_diagnostics'],
                        process_diagnostics=next((p for p in data.get('process_diagnostics',[]) if p['object_key']==student),
                            dict(available=False,items=[])))
    return response
