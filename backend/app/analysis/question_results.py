"""Verified per-question snapshots joining judging and reviewed subjective results.

This is an immutable integration boundary, never an assignment total or a grade
publication. Missing evidence remains null and every value retains its source.
"""
from collections import Counter,defaultdict
import json
from decimal import Decimal,ROUND_HALF_UP
from uuid import uuid4
from sqlalchemy import select,func
from sqlalchemy.orm import Session
from app.common.permissions import course_role,require_teacher
from app.core.errors import AppError
from app.db.base import utcnow
from app.db.models import (Assignment,AssignmentItem,AssignmentParticipant,Problem,ProblemVersion,
    ProblemVersionTag,KnowledgePoint,User,Submission,AnalysisJob,JudgeResult,TestCase,ReviewRound,ReviewAnalysis)
from app.db.models.analytics import AnalysisBatch,AnalysisInputSnapshot,AnalysisRun,AnalysisArtifact
from app.judge.config import execution_mode,runtime_profile
from app.judge.selection import Candidate,choose_best
from app.judge.local import VERDICTS,ACCEPTED
from app.peer_review.analyses import handoff
from .framework.contracts import digest,LearningInput
from .framework.service import save_output,context
from app.student.service import iso

PIPELINE='QUESTION_RESULTS'


def _capture(db,assignment_id):
    a=db.get(Assignment,assignment_id)
    if a.submission_status!='CLOSED' or a.submission_deadline>utcnow():
        raise AppError(409,'QUESTION_SCOPE_NOT_FROZEN','请关闭提交并等待提交截止到达后固定逐题结果')
    roster=list(db.scalars(select(AssignmentParticipant.student_id).where(AssignmentParticipant.assignment_id==a.id).order_by(AssignmentParticipant.student_id)))
    items=list(db.execute(select(AssignmentItem,ProblemVersion,Problem).join(ProblemVersion,ProblemVersion.id==AssignmentItem.problem_version_id)
        .join(Problem,Problem.id==ProblemVersion.problem_id).where(AssignmentItem.assignment_id==a.id).order_by(AssignmentItem.sort_order)))
    if len(roster)>300 or len(roster)*len(items)>10000:raise AppError(422,'RESULT_SCOPE_TOO_LARGE','请将逐题结果范围拆分到300位学生、10000个题目样本以内')
    users={u.id:u for u in db.scalars(select(User).where(User.id.in_(roster)))}
    item_ids=[i.id for i,_,_ in items]
    all_subs=list(db.scalars(select(Submission).where(Submission.assignment_item_id.in_(item_ids),Submission.student_id.in_(roster),
        Submission.submitted_at<a.submission_deadline).order_by(Submission.submitted_at,Submission.version_no,Submission.id)))
    groups=defaultdict(list);events=[]
    for s in all_subs:
        events.append(dict(student_key=f'student-{s.student_id}',kind='SUBMITTED',occurred_at=iso(s.submitted_at)))
        if s.withdrawn_at:events.append(dict(student_key=f'student-{s.student_id}',kind='WITHDRAWN',occurred_at=iso(s.withdrawn_at)))
        if s.status=='SUBMITTED':groups[s.assignment_item_id,s.student_id].append(s)
    results={r.submission_id:r for r in db.scalars(select(JudgeResult).join(AnalysisJob,AnalysisJob.id==JudgeResult.job_id)
        .where(JudgeResult.submission_id.in_([s.id for s in all_subs]),AnalysisJob.status=='SUCCEEDED'))}
    mode=execution_mode();profile=runtime_profile(mode);rows=[];grades=[];knowledge={}
    for item,v,p in items:
        weights={f'knowledge-{tag.knowledge_point_id}':str(tag.mastery_weight) for tag in db.scalars(select(ProblemVersionTag).where(ProblemVersionTag.problem_version_id==v.id))}
        for key in weights:
            kp=db.get(KnowledgePoint,int(key.split('-')[1]));knowledge[key]=kp.name
        candidates=None
        if p.question_type!='PROGRAMMING':
            root=db.scalar(select(ReviewRound).where(ReviewRound.assignment_item_id==item.id,ReviewRound.root_round_id.is_(None),ReviewRound.status!='CANCELLED'))
            candidates=handoff(db,root) if root else None
        peers={r['student_id']:r for r in candidates['rows']} if candidates else {}
        cases=list(db.scalars(select(TestCase).where(TestCase.test_suite_id==item.test_suite_id).order_by(TestCase.sort_order))) if item.test_suite_id else []
        equal=bool(cases) and len({c.weight for c in cases})==1 and all(c.weight>0 for c in cases)
        for uid in roster:
            submissions=groups[item.id,uid];selected=submissions[-1] if submissions else None
            score=None;reason='NO_SUBMISSION' if not selected else 'REVIEW_PENDING';source=None
            if p.question_type=='PROGRAMMING' and selected:
                eligible=[s for s in submissions if s.id in results and not results[s.id].is_mock
                    and results[s.id].execution_mode==mode and results[s.id].runtime_profile==profile
                    and results[s.id].passed_cases is not None and results[s.id].total_cases==len(cases) and len(cases)>0
                    and results[s.id].verdict in VERDICTS
                    and ((results[s.id].verdict==ACCEPTED)==(results[s.id].passed_cases==len(cases)))]
                best=choose_best([Candidate(s.id,s.version_no,s.submitted_at,results[s.id].passed_cases,
                    results[s.id].cpu_time_ms,results[s.id].memory_kib) for s in eligible])
                reason='JUDGE_EVIDENCE_UNAVAILABLE'
                if best:
                    selected=next(s for s in eligible if s.id==best.submission_id);r=results[selected.id]
                    reason='WEIGHTED_CASE_EVIDENCE_UNAVAILABLE'
                    if r.verdict==ACCEPTED and r.passed_cases==len(cases):score=Decimal(1)
                    elif equal:score=Decimal(r.passed_cases)/len(cases)
                    source=dict(kind='JUDGE_RESULT',result_id=str(r.id),submission_id=str(selected.id),execution_mode=mode,
                        runtime_profile=profile,algorithm=r.algorithm_name,algorithm_version=r.algorithm_version,
                        policy='ALL_CASES_ACCEPTED' if score==1 else 'VERIFIED_UNIFORM_CASE_WEIGHTS' if equal else 'UNAVAILABLE',
                        test_suite_id=str(item.test_suite_id),test_weights=[str(c.weight) for c in cases],passed_cases=r.passed_cases,total_cases=r.total_cases)
            elif selected and candidates:
                peer=peers.get(str(uid));score=Decimal(peer['normalized_score']) if peer and peer['normalized_score'] is not None else None
                reason=peer['reason'] if peer else 'REVIEW_PENDING'
                source=dict(kind='REVIEW_ANALYSIS',root_round_id=candidates['root_round_id'],analysis_id=candidates['analysis_id'],
                    version=candidates['version'],artifact_id=candidates['artifact_id'],output_hash=candidates['output_hash'],
                    source_hash=candidates['source_hash'],source_type=peer['source_type'] if peer else None)
                if peer and peer['submission_id']:selected=next((s for s in submissions if str(s.id)==peer['submission_id']),selected)
            if score is not None:reason=None
            row=dict(student_id=str(uid),student_name=users[uid].full_name,assignment_item_id=str(item.id),title=v.title,
                question_type=p.question_type,problem_version_id=str(v.id),max_score=str(item.max_score),
                submission_id=str(selected.id) if selected else None,normalized_score=str(score) if score is not None else None,
                item_score=str((score*item.max_score).quantize(Decimal('.01'),rounding=ROUND_HALF_UP)) if score is not None else None,
                reason=reason,source=source,knowledge_weights=weights,difficulty=v.difficulty_level)
            rows.append(row);grades.append(dict(student_key=f'student-{uid}',item_key=f'item-{item.id}',
                normalized_score=row['normalized_score'],knowledge_weights=weights,difficulty=v.difficulty_level))
    from .course_results import chapter_metadata
    return dict(assignment_id=str(a.id),assignment_title=a.title,submission_deadline=iso(a.submission_deadline),rows=rows,grades=grades,
        chapter_metadata=chapter_metadata(items),
        knowledge_labels=knowledge,roster=[f'student-{uid}' for uid in roster],events=events,execution_context=dict(mode=mode,profile=profile),is_mock=False)


def create_snapshot(db,course_id,actor,body):
    require_teacher(db,course_id,actor.id)
    a=db.get(Assignment,int(body.assignment_id))
    if a is None or a.course_id!=course_id:raise AppError(404,'NOT_FOUND','作业不存在或不可访问')
    db.scalar(select(User).where(User.id==actor.id).with_for_update())
    hashed=digest(dict(course_id=str(course_id),**body.model_dump(mode='json')))
    old=db.scalar(select(AnalysisBatch).where(AnalysisBatch.created_by==actor.id,AnalysisBatch.request_id==body.request_id))
    if old:
        if old.request_hash!=hashed or old.configuration.get('pipeline')!=PIPELINE:raise AppError(409,'IDEMPOTENCY_CONFLICT','请求标识已用于不同快照')
        return snapshot_view(db,old.id,actor)
    with Session(db.get_bind().execution_options(isolation_level='REPEATABLE READ')) as frozen:data=_capture(frozen,a.id)
    if len(str(data).encode())>8*1024*1024:raise AppError(422,'RESULT_SCOPE_TOO_LARGE','逐题结果输入超过8MiB，请拆分范围')
    batch=AnalysisBatch(course_id=course_id,assignment_id=a.id,created_by=actor.id,mode='REAL_INPUT',request_id=body.request_id,
        request_hash=hashed,seed=20261030,status='COMPLETE',configuration=dict(schema_version='analysis-v2',pipeline=PIPELINE,reason=body.reason),events={})
    db.add(batch);db.flush();version=f'question-results-{batch.id}-{digest(data)[:12]}'
    LearningInput.model_validate(dict(grades=data['grades'],results_snapshot_version=version))
    from .course_results import assignment_input
    data=dict(data,results_snapshot_version=version,ability_input_v2=assignment_input(data,version))
    if len(json.dumps(data).encode())>8*1024*1024:
        raise AppError(422,'RESULT_SCOPE_TOO_LARGE','逐题结果及章节元数据超过8MiB，请拆分范围')
    db.add(AnalysisInputSnapshot(batch_id=batch.id,scope='ROOT',input_hash=digest(data),payload=data,is_mock=False))
    run=AnalysisRun(batch_id=batch.id,step_key='result_snapshot',dependencies=[],implementation_name='verified_question_results',implementation_version='1',attempt_no=1,started_at=utcnow())
    db.add(run);db.flush()
    save_output(db,run,dict(schema_version='analysis-v2',algorithm_key='result_snapshot',implementation_name='verified_question_results',
        implementation_version='1',input_hash=digest(data),is_mock=False,status='OK',payload=data,evidence=[],limitations=['Per-question candidates only; no assignment total or grade publication.']),False)
    db.flush();return snapshot_view(db,batch.id,actor)


def _payload(db,batch):
    run=db.scalar(select(AnalysisRun).where(AnalysisRun.batch_id==batch.id,AnalysisRun.step_key=='result_snapshot',AnalysisRun.status=='SUCCEEDED'))
    artifact=db.scalar(select(AnalysisArtifact).where(AnalysisArtifact.run_id==run.id).order_by(AnalysisArtifact.id.desc()).limit(1)) if run else None
    if artifact is None or artifact.is_mock or batch.mode!='REAL_INPUT' or artifact.payload.get('is_mock') or artifact.payload.get('payload',{}).get('is_mock') or digest(artifact.payload)!=artifact.output_hash:
        raise AppError(409,'QUESTION_RESULTS_INVALID','逐题结果快照缺失或摘要不一致')
    root=db.scalar(select(AnalysisInputSnapshot).where(AnalysisInputSnapshot.batch_id==batch.id,AnalysisInputSnapshot.scope=='ROOT'))
    if (root is None or root.is_mock or digest(root.payload)!=root.input_hash
            or artifact.payload.get('input_hash')!=root.input_hash
            or artifact.payload['payload']!=root.payload):
        raise AppError(409,'QUESTION_RESULTS_INVALID','逐题结果与冻结输入不一致')
    return artifact,artifact.payload['payload']


def snapshot_view(db,batch_id,actor,limit=50,offset=0):
    batch=db.get(AnalysisBatch,batch_id)
    if batch is None or batch.configuration.get('pipeline')!=PIPELINE:raise AppError(404,'NOT_FOUND','结果快照不存在')
    role=course_role(db,batch.course_id,actor.id);artifact,payload=_payload(db,batch)
    rows=payload['rows'] if role=='TEACHER' else [r for r in payload['rows'] if r['student_id']==str(actor.id)]
    if role!='TEACHER' and not rows:raise AppError(404,'NOT_FOUND','本人不在此结果范围')
    grouped=defaultdict(list)
    for r in rows:grouped[r['assignment_item_id']].append(r)
    per_item=[]
    for iid,items in grouped.items():
        known=[Decimal(x['normalized_score']) for x in items if x['normalized_score'] is not None]
        per_item.append(dict(id=iid,title=items[0]['title'],known=len(known),missing=len(items)-len(known),
            normalized_mean=str(sum(known)/len(known)) if known else None))
    events=payload['events'] if role=='TEACHER' else [e for e in payload['events'] if e['student_key']==f'student-{actor.id}']
    visible=[]
    for row in rows:
        if role=='TEACHER':visible.append(row);continue
        safe={k:v for k,v in row.items() if k not in ('student_name','student_id')}
        safe['source']={k:v for k,v in row['source'].items() if k in ('kind','version','policy','execution_mode')} if row['source'] else None
        visible.append(safe)
    return dict(id=str(batch.id),assignment_id=payload['assignment_id'],assignment_title=payload['assignment_title'],created_at=iso(batch.created_at),
        results_snapshot_version=payload['results_snapshot_version'],role=role,is_mock=False,artifact_id=str(artifact.id),output_hash=artifact.output_hash,
        known_count=sum(r['normalized_score'] is not None for r in rows),missing_count=sum(r['normalized_score'] is None for r in rows),
        total=len(rows),rows=visible[offset:offset+limit],limit=limit,offset=offset,per_item=per_item,event_counts=dict(Counter(e['kind'] for e in events)),
        model_status=dict(mastery='NOT_IMPLEMENTED',ability='LEGACY_NOT_IMPLEMENTED',
            empirical_difficulty='NOT_IMPLEMENTED',ability_b0='AVAILABLE',ability_d1='AVAILABLE'))


def latest_view(db,course_id,actor,assignment_id=None,limit=50,offset=0):
    role=course_role(db,course_id,actor.id)
    batches=db.scalars(select(AnalysisBatch).where(AnalysisBatch.course_id==course_id,
        AnalysisBatch.configuration['pipeline'].astext==PIPELINE,*([AnalysisBatch.assignment_id==assignment_id] if assignment_id else []))
        .order_by(AnalysisBatch.id.desc()).limit(100))
    for batch in batches:
        if role!='TEACHER':
            participant=db.scalar(select(AssignmentParticipant.id).where(AssignmentParticipant.assignment_id==batch.assignment_id,AssignmentParticipant.student_id==actor.id))
            if participant is None:continue
        return snapshot_view(db,batch.id,actor,limit,offset)
    raise AppError(404,'QUESTION_RESULTS_REQUIRED','此范围尚无固定的逐题结果快照')
