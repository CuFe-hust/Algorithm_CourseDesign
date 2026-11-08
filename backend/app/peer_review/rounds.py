"""Teacher-controlled snapshot, allocation, publication and supplement lifecycle."""
from collections import Counter
from decimal import Decimal
from sqlalchemy import func, select
from app.db.base import utcnow
from app.db.models import (AssignmentItem, CourseMember, User, ReviewRound, ReviewTask, ReviewDecision)
from app.core.errors import AppError
from app.analysis.framework.contracts import digest
from app.student.service import iso
from . import core, orchestration as jobs
from .snapshots import capture, item_context, project


def _view(db,round_id,replayed=False):
    from .queries import round_view
    return dict(round_view(db,round_id),replayed=replayed)


def _round_numbers(db,item_id):
    return (db.scalar(select(func.max(ReviewRound.round_no)).where(ReviewRound.assignment_item_id==item_id)) or 0)+1


def _pairs(body,facts):
    population={r['student_id'] for r in facts['roster']}
    pairs=[]
    for pair in body.forbidden_pairs:
        a,b=sorted((str(pair.student_a_id),str(pair.student_b_id)))
        if a not in population or b not in population:
            raise AppError(422,'INVALID_FORBIDDEN_PAIR','禁止关系只能引用本次作业名单内的学生')
        pairs.append((a,b))
    if len(set(pairs))!=len(pairs):
        raise AppError(422,'DUPLICATE_FORBIDDEN_PAIR','禁止关系不能重复')
    return sorted(pairs)


def _allocation_input(data,policy,*,answers=None,existing=None,history=None,prior_loads=None,requirements=None,reviewers=None):
    selected=answers if answers is not None else data['answers']
    reviewers=reviewers if reviewers is not None else data['reviewers']
    forbidden=[]
    for a,b in policy['forbidden_pairs']:
        for answer in selected:
            other=b if answer['student_id']==a else a if answer['student_id']==b else None
            if other and data['identities'][other] in reviewers:
                forbidden.append({'answer_key':answer['answer_key'],'reviewer_key':data['identities'][other]})
    return dict(answers=[{k:a[k] for k in ('answer_key','author_key')} for a in selected],reviewers=reviewers,
        required_reviewers=policy['required_reviewers'],forbidden_edges=forbidden,existing_edges=existing or [],
        history=history or [],prior_loads=prior_loads or {},required_by_answer=requirements or {},seed=policy['seed'],
        max_tasks_per_reviewer=policy['max_tasks_per_reviewer'])


def _allocation_history(db,course_id,data):
    from app.db.models import Submission
    # Soft repetition cost only; a pinned bounded history never changes hard eligibility.
    rows=db.execute(select(Submission.student_id,ReviewTask.reviewer_id).join(ReviewTask,ReviewTask.submission_id==Submission.id)
        .join(ReviewRound,ReviewRound.id==ReviewTask.round_id).where(ReviewRound.course_id==course_id,
        ReviewRound.published_at.is_not(None)).order_by(ReviewTask.id.desc()).limit(10000)).all()
    by_author={a['student_id']:a['answer_key'] for a in data['answers']}
    reviewer_set=set(data['reviewers'])
    return [dict(answer_key=by_author[str(author)],reviewer_key=data['identities'][str(reviewer)])
        for author,reviewer in rows if str(author) in by_author and data['identities'].get(str(reviewer)) in reviewer_set]


def _initial_hash(facts,policy,deadline):
    return digest({'facts':facts,'policy':policy,'review_deadline':iso(deadline)})


def create_preview(db,item_id,actor,body):
    item_context(db,item_id,actor)
    previous,hashed=core.command(db,actor,body.request_id,'PREVIEW',{'item_id':str(item_id),**body.model_dump(mode='json')})
    if previous:return _view(db,previous.round_id,True)
    item,assignment,version,problem=item_context(db,item_id,actor,lock=True)
    old=db.scalar(select(ReviewRound).where(ReviewRound.assignment_item_id==item_id,
        ReviewRound.root_round_id.is_(None),ReviewRound.status!='CANCELLED'))
    if old:raise AppError(409,'REVIEW_ROUND_EXISTS','此题已有互评，请使用原轮次或先取消未发布预览',{'round_id':str(old.id)})
    facts=capture(db,item,assignment,version,problem)
    if body.review_deadline<=utcnow():raise AppError(422,'INVALID_REVIEW_DEADLINE','互评截止必须在未来')
    policy={**body.policy.model_dump(mode='json'),'forbidden_pairs':_pairs(body,facts),'required_reviewers':item.required_reviewers}
    if policy['minimum_samples']>item.required_reviewers or not 1<=item.required_reviewers<=10:
        raise AppError(422,'INVALID_REVIEW_POLICY','最低聚合样本数不能超过每份作品的评审人数（1～10）')
    data=project(facts)
    allocation=_allocation_input(data,policy,history=_allocation_history(db,assignment.course_id,data))
    if sum(allocation['required_reviewers'] for _ in data['answers'])>2000:
        raise AppError(422,'REVIEW_SCOPE_TOO_LARGE','单轮最多2000个评审任务，请缩小范围或减少人数')
    round_=ReviewRound(course_id=assignment.course_id,assignment_item_id=item.id,round_no=_round_numbers(db,item_id),
        created_by=actor.id,reason=body.reason.strip(),policy=policy,review_deadline=body.review_deadline,
        source_hash=_initial_hash(facts,policy,body.review_deadline))
    db.add(round_);db.flush()
    batch=jobs.create_batch(db,round_,actor,'REVIEW_ALLOCATION',{**data,'allocation_input':allocation})
    round_.allocation_batch_id=batch.id;db.flush()
    core.remember(db,actor,body.request_id,'PREVIEW',hashed,round_.id)
    return _view(db,round_.id)


def _active_reviewers(db,root,data):
    ids=[int(i) for i in data['facts']['reviewer_ids']]
    rows=db.scalars(select(User.id).join(CourseMember,CourseMember.user_id==User.id).where(
        User.id.in_(ids),User.status=='ACTIVE',CourseMember.course_id==root.course_id,
        CourseMember.status=='ACTIVE',CourseMember.role=='STUDENT').order_by(User.id))
    return [str(i) for i in rows]


def all_round_ids(db,root):
    return list(db.scalars(select(ReviewRound.id).where((ReviewRound.id==root.id)|(ReviewRound.root_round_id==root.id))))


def _supplement_manifest(db,root,data):
    tasks=list(db.execute(select(ReviewTask.id,ReviewTask.answer_key,ReviewTask.reviewer_id,ReviewTask.status)
        .where(ReviewTask.round_id.in_(all_round_ids(db,root))).order_by(ReviewTask.id)))
    decisions=list(db.scalars(select(ReviewDecision.id).where(ReviewDecision.root_round_id==root.id).order_by(ReviewDecision.id)))
    return {'source_hash':root.source_hash,'reviewer_ids':_active_reviewers(db,root,data),
        'existing_tasks':[(str(tid),a,str(uid),state) for tid,a,uid,state in tasks],
        'decision_ids':[str(i) for i in decisions]}


def publish(db,round_id,actor,body):
    core.context(db,round_id,actor)
    previous,hashed=core.command(db,actor,body.request_id,'PUBLISH',{'round_id':str(round_id),**body.model_dump(mode='json')})
    if previous:return _view(db,previous.round_id,True)
    # Lock the population before the root: student requests lock User -> root too.
    # This makes the final membership/account hash check atomic with publication.
    preview_round=db.get(ReviewRound,round_id)
    population=[int(p['student_id']) for p in core.source(db,preview_round)['facts']['roster']]
    list(db.scalars(select(User).where(User.id.in_(population)).order_by(User.id).with_for_update()))
    list(db.scalars(select(CourseMember).where(CourseMember.course_id==preview_round.course_id,
        CourseMember.user_id.in_(population)).order_by(CourseMember.user_id).with_for_update()))
    round_,root,item,assignment,version,problem=core.context(db,round_id,actor,lock=True)
    core.revision(round_,body.expected_revision)
    if round_.status!='PREVIEW':raise AppError(409,'REVIEW_NOT_PREVIEW','只允许确认尚未发布的预览')
    if round_.review_deadline<=utcnow():raise AppError(422,'INVALID_REVIEW_DEADLINE','互评截止已到，请取消并重新预览')
    data=core.source(db,round_)
    if round_.root_round_id:
        manifest=_supplement_manifest(db,root,core.source(db,root))
        actual=digest({'manifest':manifest,'policy':round_.policy,'review_deadline':iso(round_.review_deadline)})
    else:
        facts=capture(db,item,assignment,version,problem)
        actual=_initial_hash(facts,round_.policy,round_.review_deadline)
    if actual!=round_.source_hash or body.expected_source_hash!=round_.source_hash:
        raise AppError(409,'REVIEW_SOURCE_CHANGED','答案、名单、截止或既有处置已变化，请取消此预览后重新生成')
    run,artifact=jobs.output(db,round_.allocation_batch_id,'allocation')
    if artifact is None:raise AppError(409,'ALLOCATION_NOT_READY','请等待分配计算完成；失败任务可显式重试')
    if run.business_status!='OK' or not artifact.payload['payload'].get('feasible'):
        raise AppError(409,'ALLOCATION_INFEASIBLE','分配不可行，不能发布部分任务')
    # Recheck the independently validated plan against its pinned input, not a browser-provided mapping.
    from app.analysis.framework.contracts import AllocationInput,AllocationOutput
    from app.analysis.framework.validation import validate_output
    validate_output('allocation',AllocationInput.model_validate(data['allocation_input']),
        AllocationOutput.model_validate(artifact.payload['payload']))
    answers={a['answer_key']:a for a in data['answers']}
    identities={v:int(k) for k,v in data['identities'].items()}
    for edge in artifact.payload['payload']['edges']:
        answer=answers[edge['answer_key']]
        db.add(ReviewTask(round_id=round_.id,submission_id=int(answer['submission_id']),
            answer_key=answer['answer_key'],reviewer_id=identities[edge['reviewer_key']]))
    round_.status='OPEN';round_.published_at=utcnow();round_.published_by=actor.id
    core.touch(round_)
    if round_ is not root:core.touch(root)
    db.flush();jobs.human_event(db,round_.allocation_batch_id,'open_review',{
        'round_id':str(round_.id),'source_hash':round_.source_hash,'task_count':len(artifact.payload['payload']['edges']),
        'published_by':str(actor.id),'published_at':iso(round_.published_at)})
    core.remember(db,actor,body.request_id,'PUBLISH',hashed,round_.id)
    return _view(db,round_.id)


def cancel(db,round_id,actor,body):
    core.context(db,round_id,actor)
    previous,hashed=core.command(db,actor,body.request_id,'CANCEL',{'round_id':str(round_id),**body.model_dump(mode='json')})
    if previous:return _view(db,previous.round_id,True)
    round_,root,*_=core.context(db,round_id,actor,lock=True);core.revision(round_,body.expected_revision)
    if round_.status!='PREVIEW':raise AppError(409,'PUBLISHED_REVIEW_IMMUTABLE','已发布的互评不能删除或改写任务')
    round_.status='CANCELLED';round_.close_reason=body.reason;core.touch(round_)
    if round_ is not root:core.touch(root)
    from app.db.models.analytics import AnalysisBatch,AnalysisRun
    batch=db.scalar(select(AnalysisBatch).where(AnalysisBatch.id==round_.allocation_batch_id).with_for_update())
    batch.status='CANCELLED'
    for run in db.scalars(select(AnalysisRun).where(AnalysisRun.batch_id==batch.id).with_for_update()):
        if run.status not in ('SUCCEEDED','SKIPPED'):
            run.status='CANCELLED';run.attempt_token=None;run.lease_expires_at=None
    core.remember(db,actor,body.request_id,'CANCEL',hashed,round_.id)
    return _view(db,round_.id)


def extend(db,round_id,actor,body):
    core.context(db,round_id,actor)
    previous,hashed=core.command(db,actor,body.request_id,'DEADLINE',{'round_id':str(round_id),**body.model_dump(mode='json')})
    if previous:return _view(db,previous.round_id,True)
    round_,root,*_=core.context(db,round_id,actor,lock=True);core.revision(round_,body.expected_revision)
    if round_.status!='OPEN' or body.review_deadline<=utcnow() or body.review_deadline<round_.review_deadline:
        raise AppError(409,'REVIEW_DEADLINE_CONFLICT','只能为尚未封存的互评延长到未来截止')
    round_.review_deadline=body.review_deadline;core.touch(round_)
    if round_ is not root:core.touch(root)
    core.remember(db,actor,body.request_id,'DEADLINE',hashed,round_.id)
    return _view(db,round_.id)


def close(db,round_id,actor,body):
    core.context(db,round_id,actor)
    previous,hashed=core.command(db,actor,body.request_id,'CLOSE',{'round_id':str(round_id),**body.model_dump(mode='json')})
    if previous:return _view(db,previous.round_id,True)
    round_,root,*_=core.context(db,round_id,actor,lock=True);core.revision(round_,body.expected_revision)
    if round_.status!='OPEN':raise AppError(409,'REVIEW_NOT_OPEN','此轮互评不在开放状态')
    tasks=list(db.scalars(select(ReviewTask).where(ReviewTask.round_id==round_.id)))
    missing=sum(t.status!='SUBMITTED' for t in tasks)
    if missing and round_.review_deadline>utcnow() and not body.accept_incomplete:
        raise AppError(409,'INCOMPLETE_REVIEW_CONFIRMATION_REQUIRED','尚有未完成任务；提前封存需明确接受缺评并说明原因')
    round_.status='CLOSED';round_.closed_at=utcnow();round_.closed_by=actor.id;round_.close_reason=body.reason
    core.touch(round_)
    if round_ is not root:core.touch(root)
    jobs.human_event(db,round_.allocation_batch_id,'collect_reviews',{'round_id':str(round_.id),
        'closed_at':iso(round_.closed_at),'submitted_count':len(tasks)-missing,'missing_count':missing,'reason':body.reason})
    from .analyses import create_analysis
    analysis=create_analysis(db,root,actor,'INITIAL')
    core.remember(db,actor,body.request_id,'CLOSE',hashed,round_.id,analysis.id)
    return _view(db,round_.id)


def create_supplement(db,root,actor,deadline,reason):
    from .analyses import material
    if root.status!='CLOSED' or deadline<=utcnow():
        raise AppError(409,'SUPPLEMENT_NOT_READY','主轮需已封存，补评截止必须在未来')
    children=list(db.scalars(select(ReviewRound).where(ReviewRound.root_round_id==root.id)))
    if len(children)>=9 or any(c.status in ('PREVIEW','OPEN') for c in children):
        raise AppError(409,'SUPPLEMENT_LIMIT','已有待完成补评，或已达到最多9轮补评')
    data=core.source(db,root);current=material(db,root)
    counts=Counter(e['answer_key'] for e in current['evaluations'] if Decimal(e['weight'])>0)
    requirements={a['answer_key']:root.policy['required_reviewers']-counts[a['answer_key']] for a in data['answers']
        if counts[a['answer_key']]<root.policy['required_reviewers'] and a['answer_key'] not in current['overrides']}
    if not requirements:raise AppError(409,'NO_SUPPLEMENT_REQUIRED','当前有效评价数量已足够，无需补评')
    manifest=_supplement_manifest(db,root,data)
    reviewers=[data['identities'][i] for i in manifest['reviewer_ids']]
    existing=[{'answer_key':a,'reviewer_key':data['identities'][uid]} for _,a,uid,_ in manifest['existing_tasks']
        if a in requirements and data['identities'].get(uid) in reviewers]
    prior=Counter(data['identities'][uid] for _,_,uid,_ in manifest['existing_tasks'] if uid in data['identities'])
    allocation=_allocation_input(data,root.policy,answers=[a for a in data['answers'] if a['answer_key'] in requirements],
        existing=existing,prior_loads={r:prior[r] for r in reviewers},requirements=requirements,reviewers=reviewers)
    round_=ReviewRound(course_id=root.course_id,assignment_item_id=root.assignment_item_id,root_round_id=root.id,
        round_no=_round_numbers(db,root.assignment_item_id),created_by=actor.id,reason=reason,policy=root.policy,
        review_deadline=deadline,source_hash=digest({'manifest':manifest,'policy':root.policy,'review_deadline':iso(deadline)}))
    db.add(round_);db.flush()
    batch=jobs.create_batch(db,round_,actor,'REVIEW_ALLOCATION',{**data,'allocation_input':allocation,'manifest':manifest})
    round_.allocation_batch_id=batch.id;core.touch(root);db.flush()
    return round_

