"""Compose chapter-model evidence from immutable per-assignment results only."""
import json
from pydantic import ValidationError
from sqlalchemy import select,func
from app.common.permissions import require_teacher
from app.core.config import ROOT
from app.core.errors import AppError
from app.db.base import utcnow
from app.db.models import User
from app.db.models.analytics import AnalysisBatch, AnalysisInputSnapshot, AnalysisRun
from .framework.ability_contracts import AbilityInputV2
from .framework.contracts import digest
from .framework.service import save_output

PIPELINE = 'COURSE_QUESTION_RESULTS'


def chapter_metadata(items):
    """Freeze mapping and version metadata while assignment evidence is captured."""
    mapping = json.loads((ROOT/'data/analysis/question-chapter-mapping.json').read_text(encoding='utf-8'))
    taxonomy = json.loads((ROOT/'data/analysis/chapter-taxonomy.json').read_text(encoding='utf-8'))
    by_code = {q['code']: q for q in mapping['questions']}
    return dict(chapter_mapping_version=f"{mapping['mapping_version']}:{digest(mapping)}",
        chapter_taxonomy_version=f"{taxonomy['taxonomy_version']}:{digest(taxonomy)}",
        chapter_taxonomy=[{k: c[k] for k in ('order', 'code', 'name')} for c in taxonomy['axes']],
        items=[dict(item_key=f'item-{i.id}', item_code=p.code, item_version=str(v.id),
            item_type=p.question_type, difficulty=v.difficulty_level, max_score=str(i.max_score),
            chapter_weights={k: str(w) for k,w in by_code.get(p.code, {}).get('chapter_weights', {}).items()})
            for i,v,p in items])


def assignment_input(data, version):
    metadata = data['chapter_metadata']
    pairs, grades = [], []
    for row in data['rows']:
        student, item = f"student-{row['student_id']}", f"item-{row['assignment_item_id']}"
        state = ('SCORED' if row['normalized_score'] is not None else
            'NOT_SUBMITTED' if row['reason'] == 'NO_SUBMISSION' else
            'PENDING' if row['reason'] in ('REVIEW_PENDING', 'MINIMUM_SAMPLES_NOT_MET') else 'INVALID')
        pairs.append(dict(student_key=student, item_key=item, state=state))
        if state == 'SCORED':
            grades.append(dict(student_key=student, item_key=item, normalized_score=row['normalized_score'],
                score_version=digest(row['source']), result_ref=f"{version}:{student}:{item}",
                score_kind=row['source']['kind']))
    return AbilityInputV2.model_validate(dict(source_kind='DATABASE', results_snapshot_version=version,
        scoring_policy_version='verified-question-evidence-v1', **metadata,
        scope=dict(scope_kind='COURSE', scope_label='课程章节证据（单次已固定作业）',
            student_keys=data['roster'], assignment_ids=[data['assignment_id']], expected_pairs=pairs),
        grades=grades)).model_dump(mode='json')


def create_snapshot(db, course_id, actor, body):
    from .question_results import _payload
    require_teacher(db, course_id, actor.id)
    db.scalar(select(User).where(User.id == actor.id).with_for_update())
    hashed = digest(dict(course_id=str(course_id), pipeline=PIPELINE, **body.model_dump(mode='json')))
    old = db.scalar(select(AnalysisBatch).where(AnalysisBatch.created_by == actor.id,
        AnalysisBatch.request_id == body.request_id))
    if old:
        if old.request_hash != hashed:
            raise AppError(409, 'IDEMPOTENCY_CONFLICT', '请求标识已用于不同输入')
        return view(db, old)
    query = select(AnalysisBatch).where(AnalysisBatch.course_id == course_id,
        AnalysisBatch.configuration['pipeline'].astext == 'QUESTION_RESULTS',
        AnalysisBatch.status == 'COMPLETE').order_by(AnalysisBatch.id.desc())
    if body.source_batch_ids:
        query = query.where(AnalysisBatch.id.in_([int(i) for i in body.source_batch_ids]))
    else:
        latest = select(func.max(AnalysisBatch.id)).where(AnalysisBatch.course_id == course_id,
            AnalysisBatch.configuration['pipeline'].astext == 'QUESTION_RESULTS',
            AnalysisBatch.status == 'COMPLETE').group_by(AnalysisBatch.assignment_id)
        query = query.where(AnalysisBatch.id.in_(latest)).limit(101)
    sources = list(db.scalars(query))
    if body.source_batch_ids and len(sources) != len(body.source_batch_ids):
        raise AppError(404, 'NOT_FOUND', '来源快照不存在或不属于当前课程')
    # Auto mode takes exactly the latest version of each assignment. Explicit
    # selection may pick historical versions but may never double-count a task.
    selected = {}
    for source in sources:
        if source.assignment_id in selected:
            if body.source_batch_ids:
                raise AppError(422, 'DUPLICATE_ASSIGNMENT_SOURCE', '同一作业只能采用一个结果版本')
            continue
        selected[source.assignment_id] = source
    if not selected:
        raise AppError(409, 'QUESTION_RESULTS_REQUIRED', '请先固定至少一次作业的逐题结果')
    if len(selected) > 100:
        raise AppError(422, 'ANALYSIS_SCOPE_TOO_LARGE', '课程快照最多包含100次作业，请显式选择范围')
    inputs, refs, input_bytes = [], [], 0
    for source in selected.values():
        artifact, payload = _payload(db, source)
        data = payload.get('ability_input_v2')
        if data is None:
            raise AppError(409, 'CHAPTER_METADATA_REQUIRED', f'作业结果快照 #{source.id} 缺少冻结章节元数据，请重新固定该作业的逐题结果')
        input_bytes += len(json.dumps(data).encode())
        if input_bytes > 8*1024*1024:
            raise AppError(422, 'ANALYSIS_SCOPE_TOO_LARGE', '课程快照超过8MiB，请选择较小范围')
        try:
            typed = AbilityInputV2.model_validate(data)
        except ValidationError:
            raise AppError(409, 'QUESTION_RESULTS_INVALID', '来源章节契约不完整') from None
        if typed.source_kind != 'DATABASE' or typed.scope.assignment_ids != [str(source.assignment_id)]:
            raise AppError(409, 'QUESTION_RESULTS_INVALID', '来源范围或标记不一致')
        inputs.append(typed.model_dump(mode='json'))
        refs.append(dict(batch_id=str(source.id), assignment_id=str(source.assignment_id),
            artifact_id=str(artifact.id), output_hash=artifact.output_hash))
    first = inputs[0]
    keys = ('chapter_taxonomy_version', 'chapter_mapping_version', 'scoring_policy_version', 'chapter_taxonomy')
    if any(any(data[k] != first[k] for k in keys) for data in inputs):
        raise AppError(409, 'CHAPTER_VERSION_CONFLICT', '章节映射或计分政策版本不同，请重新固定为一致版本')
    students = sorted({s for data in inputs for s in data['scope']['student_keys']})
    pairs = [p for data in inputs for p in data['scope']['expected_pairs']]
    if len(students) > 300 or len(pairs) > 10000:
        raise AppError(422, 'ANALYSIS_SCOPE_TOO_LARGE', '课程范围最多300名学生、10000个学生题目样本，请选择较小范围')
    data = dict(**{k:first[k] for k in keys}, source_kind='DATABASE',
        results_snapshot_version=f'course-results-{digest(refs)}',
        scope=dict(scope_kind='COURSE', scope_label=f'课程累计章节表现（已固定的{len(inputs)}次作业）',
            student_keys=students, assignment_ids=[str(i) for i in sorted(selected)], expected_pairs=pairs),
        items=[i for data in inputs for i in data['items']], grades=[g for data in inputs for g in data['grades']])
    data = AbilityInputV2.model_validate(data).model_dump(mode='json')
    payload = dict(is_mock=False, ability_input_v2=data, sources=refs, reason=body.reason)
    if len(json.dumps(payload).encode()) > 8*1024*1024:
        raise AppError(422, 'ANALYSIS_SCOPE_TOO_LARGE', '课程快照超过8MiB，请选择较小范围')
    batch = AnalysisBatch(course_id=course_id, created_by=actor.id, mode='REAL_INPUT', status='COMPLETE',
        request_id=body.request_id, request_hash=hashed, seed=20261030,
        configuration=dict(schema_version='analysis-v2', pipeline=PIPELINE, scope_kind='COURSE'), events={})
    db.add(batch); db.flush()
    db.add(AnalysisInputSnapshot(batch_id=batch.id, scope='ROOT', payload=payload, input_hash=digest(payload), is_mock=False))
    run = AnalysisRun(batch_id=batch.id, step_key='result_snapshot', dependencies=[],
        implementation_name='frozen_course_results', implementation_version='1', attempt_no=1, started_at=utcnow())
    db.add(run); db.flush()
    save_output(db, run, dict(schema_version='analysis-v2', algorithm_key='result_snapshot',
        implementation_name='frozen_course_results', implementation_version='1', input_hash=digest(payload),
        is_mock=False, status='OK', payload=payload, evidence=[], limitations=['Only selected frozen assignment evidence; no grade publication.']), False)
    db.flush()
    return view(db, batch)


def view(db, batch):
    from .question_results import _payload
    artifact, payload = _payload(db, batch)
    data = payload['ability_input_v2']
    return dict(id=str(batch.id), results_snapshot_version=data['results_snapshot_version'],
        source_count=len(payload['sources']), student_count=len(data['scope']['student_keys']),
        known_count=len(data['grades']), total=len(data['scope']['expected_pairs']),
        output_hash=artifact.output_hash, is_mock=False)
