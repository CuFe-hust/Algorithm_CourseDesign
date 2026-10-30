from sqlalchemy import select,func
from app.db.models import ReviewRound,ReviewTask,ReviewEvaluation,ReviewAnalysis,ReviewDecision,ReviewCommand,AssignmentItem,Assignment,ProblemVersion,Problem
from app.db.models.analytics import AnalysisRun,AnalysisInputSnapshot
from app.common.permissions import require_teacher,course_role
from app.core.errors import AppError
from app.student.service import iso
from . import core,orchestration as jobs
from .analyses import latest,handoff
from .snapshots import item_context


def analysis_view(db,a):
    runs=[]
    for r in db.scalars(select(AnalysisRun).where(AnalysisRun.batch_id==a.batch_id).order_by(AnalysisRun.id)):
        _,artifact=jobs.output(db,a.batch_id,r.step_key)
        runs.append(dict(id=str(r.id),key=r.step_key,status=r.status,business_status=r.business_status,
            reason=r.reason,implementation=r.implementation_name,implementation_version=r.implementation_version,
            output=artifact.payload['payload'] if artifact else None,limitations=artifact.payload.get('limitations',[]) if artifact else []))
    return dict(id=str(a.id),version=a.version_no,kind=a.kind,batch_id=str(a.batch_id),source_hash=a.source_hash,
        resolved_at=iso(a.resolved_at),resolution_reason=a.resolution_reason,acknowledged_statuses=a.acknowledged_statuses,runs=runs,
        decisions=[dict(id=str(d.id),action=d.action,evaluation_id=str(d.evaluation_id) if d.evaluation_id else None,
            answer_key=d.answer_key,weight=str(d.weight) if d.weight is not None else None,override_score=str(d.override_score) if d.override_score is not None else None,
            reason=d.reason,created_by=str(d.created_by),created_at=iso(d.created_at)) for d in db.scalars(select(ReviewDecision).where(ReviewDecision.analysis_id==a.id).order_by(ReviewDecision.id))])


def round_view(db,round_id):
    r=db.get(ReviewRound,round_id);root=core.root_round(db,r);data=core.source(db,r)
    run,artifact=jobs.output(db,r.allocation_batch_id,'allocation')
    counts=dict(db.execute(select(ReviewTask.status,func.count()).where(ReviewTask.round_id==r.id).group_by(ReviewTask.status)).all())
    a=latest(db,root)
    return dict(id=str(r.id),root_round_id=str(root.id),assignment_item_id=str(r.assignment_item_id),round_no=r.round_no,
        assignment_title=data['facts'].get('assignment_title',db.get(Assignment,int(data['facts']['assignment_id'])).title),status=r.status,revision=r.revision_no,root_revision=root.revision_no,source_hash=r.source_hash,policy=r.policy,
        review_deadline=iso(r.review_deadline),published_at=iso(r.published_at),closed_at=iso(r.closed_at),reason=r.reason,
        question=data['facts']['question'],rubric=data['facts']['rubric'],item_max_score=data['facts']['item_max_score'],
        answer_count=len(data['allocation_input']['answers']),reviewer_count=len(data['allocation_input']['reviewers']),
        task_counts=counts,allocation=dict(batch_id=str(r.allocation_batch_id),run_id=str(run.id),status=run.status,business_status=run.business_status,
            output=artifact.payload['payload'] if artifact else None),
        latest_analysis=analysis_view(db,a) if a else None,
        analyses=[dict(id=str(x.id),version=x.version_no,kind=x.kind,resolved_at=iso(x.resolved_at)) for x in db.scalars(
            select(ReviewAnalysis).where(ReviewAnalysis.root_round_id==root.id).order_by(ReviewAnalysis.version_no.desc()).limit(30))],
        rounds=[dict(id=str(x.id),round_no=x.round_no,status=x.status) for x in db.scalars(select(ReviewRound).where(
            (ReviewRound.id==root.id)|(ReviewRound.root_round_id==root.id)).order_by(ReviewRound.round_no))],
        audit=[dict(id=str(c.id),actor_id=str(c.actor_id),operation=c.operation,payload=c.payload,created_at=iso(c.created_at)) for c in db.scalars(select(ReviewCommand).where(ReviewCommand.round_id.in_([root.id,r.id])).order_by(ReviewCommand.id.desc()).limit(30))],
        candidates=handoff(db,root))


def list_rounds(db,course_id,actor,limit,offset):
    require_teacher(db,course_id,actor.id)
    where=ReviewRound.course_id==course_id
    rows=db.scalars(select(ReviewRound).where(where).order_by(ReviewRound.id.desc()).limit(limit).offset(offset))
    return dict(total=db.scalar(select(func.count()).select_from(ReviewRound).where(where)),items=[dict(id=str(r.id),
        assignment_item_id=str(r.assignment_item_id),root_round_id=str(r.root_round_id or r.id),round_no=r.round_no,
        status=r.status,review_deadline=iso(r.review_deadline)) for r in rows])


def options(db,item_id,actor):
    item,a,v,p=item_context(db,item_id,actor)
    return dict(assignment_item_id=str(item.id),question_title=v.title,submission_status=a.submission_status,
        submission_deadline=iso(a.submission_deadline),review_deadline=iso(a.review_deadline),required_reviewers=item.required_reviewers,
        item_max_score=str(item.max_score))


def task_rows(db,round_id,actor,limit,offset):
    r,*_=core.context(db,round_id,actor)
    rows=db.execute(select(ReviewTask,ReviewEvaluation).outerjoin(ReviewEvaluation,ReviewEvaluation.task_id==ReviewTask.id)
        .where(ReviewTask.round_id==r.id).order_by(ReviewTask.id).limit(limit).offset(offset))
    return dict(items=[dict(task_id=str(t.id),answer_key=t.answer_key,reviewer_id=str(t.reviewer_id),status=t.status,
        evaluation_id=str(e.id) if e else None,total_score=str(e.total_score) if e else None,
        elapsed_seconds=str(e.elapsed_seconds) if e else None) for t,e in rows],
        total=db.scalar(select(func.count()).select_from(ReviewTask).where(ReviewTask.round_id==r.id)))


def student_tasks(db,course_id,actor,limit,offset):
    if course_role(db,course_id,actor.id)!='STUDENT':raise AppError(403,'STUDENT_REQUIRED','请使用本课程学生身份')
    where=(ReviewTask.reviewer_id==actor.id,ReviewRound.course_id==course_id)
    rows=db.execute(select(ReviewTask,ReviewRound,ProblemVersion.title,Assignment.title).join(ReviewRound,ReviewTask.round_id==ReviewRound.id)
        .join(AssignmentItem,AssignmentItem.id==ReviewRound.assignment_item_id).join(Assignment,Assignment.id==AssignmentItem.assignment_id).join(ProblemVersion,ProblemVersion.id==AssignmentItem.problem_version_id)
        .where(*where).order_by(ReviewTask.id.desc()).limit(limit).offset(offset))
    return dict(items=[dict(id=str(t.id),round_id=str(r.id),round_no=r.round_no,title=title,assignment_title=assignment_title,status=t.status,
        round_status=r.status,review_deadline=iso(r.review_deadline)) for t,r,title,assignment_title in rows],
        total=db.scalar(select(func.count()).select_from(ReviewTask).join(ReviewRound,ReviewTask.round_id==ReviewRound.id).where(*where)))
