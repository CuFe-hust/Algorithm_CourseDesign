"""Student-only anonymous projection. All elapsed times originate on the server."""
from decimal import Decimal, ROUND_DOWN
from sqlalchemy import select
from app.db.models import ReviewTask,ReviewRound,ReviewEvaluation,User,Assignment
from app.common.permissions import course_role
from app.core.errors import AppError
from app.db.base import utcnow
from app.analysis.framework.contracts import digest
from app.student.service import iso
from . import core


def owned(db,task_id,actor,lock=False):
    task=db.get(ReviewTask,task_id)
    round_=db.get(ReviewRound,task.round_id) if task else None
    if round_ is None or task.reviewer_id!=actor.id or course_role(db,round_.course_id,actor.id)!='STUDENT':
        raise AppError(404,'NOT_FOUND','评审任务不存在或不可访问')
    if lock:
        db.scalar(select(User).where(User.id==actor.id).with_for_update())
        root=db.scalar(select(ReviewRound).where(ReviewRound.id==(round_.root_round_id or round_.id)).with_for_update().execution_options(populate_existing=True))
        round_=root if root.id==round_.id else db.scalar(select(ReviewRound).where(ReviewRound.id==round_.id).with_for_update().execution_options(populate_existing=True))
        task=db.scalar(select(ReviewTask).where(ReviewTask.id==task_id).with_for_update().execution_options(populate_existing=True))
    return task,round_


def evaluation_view(e):
    return dict(id=str(e.id),scores=e.dimension_scores,total_score=str(e.total_score),comment=e.comment,
        opened_at=iso(e.opened_at),submitted_at=iso(e.submitted_at),elapsed_seconds=str(e.elapsed_seconds))


def detail(db,task,round_):
    source=core.source(db,round_);facts=source['facts']
    answer=next(a for a in facts['answers'] if a['submission_id']==str(task.submission_id))
    if answer['student_id']==str(task.reviewer_id):raise AppError(409,'INVALID_REVIEW_TASK','自评任务不可使用')
    e=db.scalar(select(ReviewEvaluation).where(ReviewEvaluation.task_id==task.id))
    return dict(id=str(task.id),assignment_title=facts.get('assignment_title',db.get(Assignment,int(facts['assignment_id'])).title),round_id=str(round_.id),round_no=round_.round_no,status=task.status,
        round_status=round_.status,review_deadline=iso(round_.review_deadline),opened_at=iso(task.opened_at),
        server_time=iso(utcnow()),question=facts['question'],answer_content=answer['content'],rubric=facts['rubric'],
        rubric_max=facts['rubric_max'],evaluation=evaluation_view(e) if e else None,
        can_submit=round_.status=='OPEN' and round_.review_deadline>utcnow() and e is None)


def open_task(db,task_id,actor):
    task,round_=owned(db,task_id,actor,True)
    if task.opened_at is None and round_.status=='OPEN' and round_.review_deadline>utcnow():task.opened_at=utcnow();db.flush()
    return detail(db,task,round_)


def submit(db,task_id,actor,body):
    task,round_=owned(db,task_id,actor,True)
    normalized=dict(task_id=str(task.id),scores=sorted([dict(rubric_item_id=str(s.rubric_item_id),score=str(s.score)) for s in body.scores],key=lambda s:int(s['rubric_item_id'])),comment=body.comment)
    hashed=digest(normalized)
    existing=db.scalar(select(ReviewEvaluation).where(ReviewEvaluation.reviewer_id==actor.id,ReviewEvaluation.client_request_id==body.client_request_id))
    if existing:
        if existing.request_hash!=hashed:raise AppError(409,'IDEMPOTENCY_CONFLICT','同一提交标识不能用于不同评分')
        return dict(detail(db,task,round_),replayed=True)
    if db.scalar(select(ReviewEvaluation.id).where(ReviewEvaluation.task_id==task.id)):
        raise AppError(409,'EVALUATION_IMMUTABLE','此任务已提交，原始评价不可改写')
    now=utcnow()
    if round_.status!='OPEN' or round_.review_deadline<=now:raise AppError(409,'REVIEW_CLOSED','此轮互评已截止或封存')
    if task.opened_at is None:raise AppError(409,'TASK_NOT_OPENED','请先打开并阅读此评审任务')
    source=core.source(db,round_);rubric={int(d['id']):d for d in source['facts']['rubric']}
    if {s.rubric_item_id for s in body.scores}!=set(rubric):raise AppError(422,'RUBRIC_MISMATCH','必须且只能提交冻结量表中的全部维度')
    if any(s.score>Decimal(rubric[s.rubric_item_id]['max_score']) for s in body.scores):raise AppError(422,'SCORE_OUT_OF_RANGE','分项得分超过量表范围')
    own_answer=next(a for a in source['facts']['answers'] if a['submission_id']==str(task.submission_id))
    if own_answer['student_id']==str(actor.id):raise AppError(409,'INVALID_REVIEW_TASK','不能评审自己的作品')
    delta=now-task.opened_at
    seconds=Decimal(delta.days*86400+delta.seconds)+Decimal(delta.microseconds)/1000000
    if seconds<0:raise AppError(503,'CLOCK_UNAVAILABLE','服务器时钟异常，请稍后重试')
    db.add(ReviewEvaluation(task_id=task.id,reviewer_id=actor.id,client_request_id=body.client_request_id,
        request_hash=hashed,dimension_scores=normalized['scores'],total_score=sum(s.score for s in body.scores),
        comment=body.comment,opened_at=task.opened_at,submitted_at=now,elapsed_seconds=seconds.quantize(Decimal('.001'),rounding=ROUND_DOWN)))
    task.status='SUBMITTED';task.submitted_at=now;db.flush()
    return dict(detail(db,task,round_),replayed=False)
