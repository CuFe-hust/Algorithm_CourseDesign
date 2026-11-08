"""Append-only analysis versions and explicit, audited teacher resolutions."""
from decimal import Decimal, ROUND_HALF_UP
from sqlalchemy import select, func
from app.core.errors import AppError
from app.db.base import utcnow
from app.db.models import ReviewRound,ReviewTask,ReviewEvaluation,ReviewDecision,ReviewAnalysis
from app.db.models.analytics import AnalysisInputSnapshot
from app.analysis.framework.contracts import digest
from . import core, orchestration as jobs
from .snapshots import anonymous


def latest(db,root):
    return db.scalar(select(ReviewAnalysis).where(ReviewAnalysis.root_round_id==root.id)
        .order_by(ReviewAnalysis.version_no.desc()).limit(1))


def material(db,root):
    ids=list(db.scalars(select(ReviewRound.id).where(((ReviewRound.id==root.id)|(ReviewRound.root_round_id==root.id)),
        ReviewRound.status=='CLOSED')))
    tasks=list(db.scalars(select(ReviewTask).where(ReviewTask.round_id.in_(ids)).order_by(ReviewTask.id)))
    by_id={t.id:t for t in tasks}
    weights={};overrides={};decision_ids=[]
    for d in db.scalars(select(ReviewDecision).where(ReviewDecision.root_round_id==root.id).order_by(ReviewDecision.id)):
        decision_ids.append(str(d.id))
        if d.evaluation_id:
            weights[d.evaluation_id]=str(d.weight if d.action=='DOWNWEIGHT' else 0 if d.action=='INVALIDATE' else 1)
        elif d.action=='OVERRIDE':overrides[d.answer_key]=str(d.override_score)
        else:overrides.pop(d.answer_key,None)
    evaluations=[];durations={};identities=core.source(db,root)['identities']
    for e in db.scalars(select(ReviewEvaluation).where(ReviewEvaluation.task_id.in_(by_id)).order_by(ReviewEvaluation.id)):
        evaluations.append(dict(evaluation_key=str(e.id),answer_key=by_id[e.task_id].answer_key,
            reviewer_key=identities[str(e.reviewer_id)],score=str(e.total_score),weight=weights.get(e.id,'1')))
        durations[e.task_id]=str(e.elapsed_seconds)
    return dict(evaluations=evaluations,overrides=overrides,decision_ids=decision_ids,
        timings=[dict(task_key=str(t.id),elapsed_seconds=durations.get(t.id)) for t in tasks],
        tasks=[dict(task_id=str(t.id),answer_key=t.answer_key,reviewer_key=identities[str(t.reviewer_id)],status=t.status) for t in tasks])


def history(db,root,data):
    """Only resolved, frozen earlier initial baselines; never future/current-root data."""
    histories=[];baselines=[];authors={}
    current=set(data['reviewers']);scale=Decimal(data['facts']['rubric_max'])
    roots=list(db.scalars(select(ReviewRound).where(ReviewRound.course_id==root.course_id,
        ReviewRound.root_round_id.is_(None),ReviewRound.id!=root.id).order_by(ReviewRound.id.desc()).limit(20)))
    for other in roots:
        old=db.scalar(select(ReviewAnalysis).where(ReviewAnalysis.root_round_id==other.id,
            ReviewAnalysis.kind=='INITIAL',ReviewAnalysis.resolved_at.is_not(None),ReviewAnalysis.created_at<root.created_at)
            .order_by(ReviewAnalysis.version_no.desc()).limit(1))
        if old is None:continue
        _,artifact=jobs.output(db,old.batch_id,'aggregation')
        if artifact is None:continue
        snap=db.scalar(select(AnalysisInputSnapshot).where(AnalysisInputSnapshot.batch_id==old.batch_id,AnalysisInputSnapshot.scope=='ROOT'))
        if snap is None or digest(snap.payload)!=snap.input_hash:raise AppError(409,'REVIEW_SNAPSHOT_INVALID','历史基准快照无效')
        olddata=snap.payload
        # Historical comparisons exclude the target reviewer from the reference median.
        # Each immutable evaluation gets its own reference key, so its own score cannot
        # pull the baseline toward itself. At most one assignment per answer/reviewer exists.
        from statistics import median
        oldscale=Decimal(olddata['aggregation_input']['rubric_max'])
        oldevals=olddata['aggregation_input']['evaluations']
        picked=[e for e in oldevals if e['reviewer_key'] in current
            and olddata['author_map'].get(e['answer_key']) in current and Decimal(e['weight'])>0]
        if len(histories)+len(picked)>1000:break
        for e in picked:
            peers=[Decimal(p['score'])/oldscale for p in oldevals if p['answer_key']==e['answer_key']
                and p['reviewer_key']!=e['reviewer_key'] and Decimal(p['weight'])>0]
            if len(peers)<root.policy['deviation_minimum_peers']:continue
            key='h_'+e['evaluation_key']
            histories.append(dict(e,answer_key=key,score=str(Decimal(e['score'])/oldscale*scale)))
            baselines.append(dict(answer_key=key,normalized_score=str(median(peers)),valid_count=len(peers),dispersion=None,reason=None))
            authors[key]=olddata['author_map'][e['answer_key']]
    return histories,baselines,authors


def create_analysis(db,root,actor,kind):
    if root.status!='CLOSED' or db.scalar(select(ReviewRound.id).where(ReviewRound.root_round_id==root.id,
        ReviewRound.status.in_(['PREVIEW','OPEN'])).limit(1)):
        raise AppError(409,'REVIEWS_NOT_FROZEN','所有互评轮次封存后才能分析')
    data=core.source(db,root);raw=material(db,root);policy=root.policy
    previous=latest(db,root);version=previous.version_no+1 if previous else 1
    author_map={a['answer_key']:a['author_key'] for a in data['answers']}
    hist,histbase,histauthors=history(db,root,data) if kind=='INITIAL' else ([],[],{})
    base=dict(evaluations=raw['evaluations'],history=hist,history_baseline=histbase,
        author_map={**histauthors,**author_map},rubric_max=data['facts']['rubric_max'],edges=[])
    detection={key:dict(base,minimum_samples=policy['history_minimum_samples'] if key=='reviewer_bias' else policy['deviation_minimum_peers'],
        threshold=policy['bias_threshold'] if key=='reviewer_bias' else policy['deviation_threshold']) for key in ('deviation','reviewer_bias','relationship')}
    payload=dict(root_round_id=str(root.id),analysis_version=version,facts=data['facts'],answers=data['answers'],
        policy=policy,author_map=author_map,material_hash=digest(raw),raw_material=raw,
        aggregation_input=dict(answers=list(author_map),rubric_max=data['facts']['rubric_max'],minimum_samples=policy['minimum_samples'],
            evaluations=raw['evaluations'],method=policy['aggregation_method']),
        timing_input=dict(timings=raw['timings'],minimum_samples=policy['timing_minimum_samples'],short_seconds=policy['short_seconds'],
            relative_fraction=policy['timing_relative_fraction']),detection_inputs=detection,overrides=raw['overrides'])
    batch=jobs.create_batch(db,root,actor,'REVIEW_ANALYSIS' if kind=='INITIAL' else 'REVIEW_RECOMPUTE',payload)
    analysis=ReviewAnalysis(root_round_id=root.id,version_no=version,kind=kind,batch_id=batch.id,
        source_hash=digest(payload),created_by=actor.id)
    db.add(analysis);db.flush();return analysis


def effective_output(payload,root):
    scores=[];maximum=Decimal(root['facts']['item_max_score'])
    for score in payload['scores']:
        override=root['overrides'].get(score['answer_key'])
        normalized=Decimal(override)/maximum if override is not None else (
            Decimal(score['normalized_score']) if score['normalized_score'] is not None else None)
        scores.append(dict(score,raw_normalized_score=score['normalized_score'],
            normalized_score=str(normalized) if normalized is not None else None,
            item_score=str((normalized*maximum).quantize(Decimal('.01'),rounding=ROUND_HALF_UP)) if normalized is not None else None,
            source_type='TEACHER_OVERRIDE' if override is not None else 'PEER_AGGREGATION',
            reason=None if normalized is not None else score['reason']))
    return dict(scores=scores,analysis_version=root['analysis_version'],root_round_id=root['root_round_id'],
        material_hash=root['material_hash'],is_mock=False,policy=root['policy'])


def resolve(db,analysis_id,actor,body):
    a=db.get(ReviewAnalysis,analysis_id)
    if a is None:raise AppError(404,'NOT_FOUND','分析版本不存在')
    core.context(db,a.root_round_id,actor)
    old,hashed=core.command(db,actor,body.request_id,'RESOLVE',{'analysis_id':str(analysis_id),**body.model_dump(mode='json')})
    from .rounds import _view,create_supplement
    if old:return _view(db,old.round_id,True)
    _,root,*_=core.context(db,a.root_round_id,actor,lock=True);core.revision(root,body.expected_revision)
    if latest(db,root).id!=a.id or a.kind!='INITIAL' or a.resolved_at is not None:
        raise AppError(409,'ANALYSIS_NOT_CURRENT','只能复核当前尚未处置的初步分析版本')
    if body.expected_source_hash!=a.source_hash:raise AppError(409,'REVIEW_SOURCE_CHANGED','分析输入摘要不一致')
    statuses={}
    for key in jobs.DETECTORS:
        run,artifact=jobs.output(db,a.batch_id,key)
        if artifact is None:raise AppError(409,'DETECTION_NOT_READY','请等待四类检测全部完成')
        statuses[key]=run.business_status
    if body.acknowledged_statuses!=statuses:raise AppError(409,'DETECTION_ACK_REQUIRED','请确认四类检测的实际状态，包括证据不足')
    snapshot=db.scalar(select(AnalysisInputSnapshot).where(AnalysisInputSnapshot.batch_id==a.batch_id,AnalysisInputSnapshot.scope=='ROOT'))
    if snapshot is None or digest(snapshot.payload)!=snapshot.input_hash or snapshot.payload['material_hash']!=digest(material(db,root)):
        raise AppError(409,'REVIEW_SOURCE_CHANGED','原始评价或处置已变化，请重新分析')
    data=snapshot.payload;evals={e['evaluation_key'] for e in data['aggregation_input']['evaluations']};answers=set(data['author_map'])
    for d in body.decisions:
        if (d.evaluation_id is not None and str(d.evaluation_id) not in evals) or (d.answer_key and d.answer_key not in answers):
            raise AppError(422,'INVALID_DECISION_TARGET','处置只能引用本分析输入内的评价或作品')
        if d.override_score is not None and d.override_score>Decimal(data['facts']['item_max_score']):
            raise AppError(422,'OVERRIDE_OUT_OF_RANGE','教师改分不得超过本题满分')
        db.add(ReviewDecision(root_round_id=root.id,analysis_id=a.id,created_by=actor.id,**d.model_dump()))
    a.resolved_at=utcnow();a.resolved_by=actor.id;a.resolution_reason=body.reason;a.acknowledged_statuses=statuses
    db.flush();jobs.human_event(db,a.batch_id,'resolve',dict(analysis_id=str(a.id),reason=body.reason,
        acknowledged_statuses=statuses,decision_count=len(body.decisions),request_supplement=body.request_supplement))
    core.touch(root)
    if body.request_supplement:create_supplement(db,root,actor,body.supplement_deadline,body.reason)
    else:create_analysis(db,root,actor,'RECOMPUTE')
    core.remember(db,actor,body.request_id,'RESOLVE',hashed,root.id,a.id)
    return _view(db,root.id)


def reanalyze(db,round_id,actor,body):
    core.context(db,round_id,actor)
    old,hashed=core.command(db,actor,body.request_id,'REANALYZE',{'round_id':str(round_id),**body.model_dump(mode='json')})
    from .rounds import _view
    if old:return _view(db,old.round_id,True)
    _,root,*_=core.context(db,round_id,actor,lock=True);core.revision(root,body.expected_revision)
    previous=latest(db,root)
    if previous and previous.kind=='INITIAL' and previous.resolved_at is None:
        raise AppError(409,'ANALYSIS_UNRESOLVED','请先完成当前初步分析的复核')
    a=create_analysis(db,root,actor,'INITIAL');core.touch(root)
    core.remember(db,actor,body.request_id,'REANALYZE',hashed,root.id,a.id)
    return _view(db,root.id)


def handoff(db,root):
    a=latest(db,root)
    pending=db.scalar(select(ReviewRound.id).where(ReviewRound.root_round_id==root.id,ReviewRound.status.in_(['PREVIEW','OPEN'])).limit(1))
    artifact=None
    if a and a.kind=='RECOMPUTE' and not pending:_,artifact=jobs.output(db,a.batch_id,'effective_subjective_results')
    data=core.source(db,root);by_student={ans['student_id']:ans for ans in data['answers']}
    by_key={s['answer_key']:s for s in artifact.payload['payload']['scores']} if artifact else {}
    rows=[]
    for person in data['facts']['roster']:
        answer=by_student.get(person['student_id']);score=by_key.get(answer['answer_key']) if answer else None
        rows.append(dict(student_id=person['student_id'],assignment_item_id=str(root.assignment_item_id),
            submission_id=answer['submission_id'] if answer else None,answer_key=answer['answer_key'] if answer else None,
            normalized_score=score['normalized_score'] if score else None,item_score=score['item_score'] if score else None,
            reason=score['reason'] if score else 'NO_SUBMISSION' if answer is None else 'REVIEW_PENDING',
            source_type=score['source_type'] if score else None,valid_count=score['valid_count'] if score else 0))
    return dict(schema_version='subjective-candidates-v1',is_mock=False,status='READY' if artifact else 'WAITING_INPUT',
        root_round_id=str(root.id),analysis_id=str(a.id) if a else None,version=a.version_no if a else None,
        source_hash=a.source_hash if a else None,artifact_id=str(artifact.id) if artifact else None,
        output_hash=artifact.output_hash if artifact else None,policy=root.policy,rows=rows)
