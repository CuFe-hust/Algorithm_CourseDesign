"""Shared authorization, locking, immutable source and command idempotency."""
from sqlalchemy import select
from app.common.permissions import require_teacher
from app.core.errors import AppError
from app.db.models import AssignmentItem, User, ReviewRound, ReviewCommand
from app.db.models.analytics import AnalysisInputSnapshot
from app.analysis.framework.contracts import digest
from .snapshots import item_context


def command(db,actor,request_id,operation,data):
    db.scalar(select(User).where(User.id==actor.id).with_for_update().execution_options(populate_existing=True))
    hashed=digest({'operation':operation,'data':data})
    previous=db.scalar(select(ReviewCommand).where(ReviewCommand.actor_id==actor.id,ReviewCommand.request_id==request_id))
    if previous and previous.request_hash!=hashed:
        raise AppError(409,'IDEMPOTENCY_CONFLICT','同一请求标识不能用于不同互评操作或内容')
    db.info['review_command_payload'] = data
    return previous,hashed


def remember(db,actor,request_id,operation,hashed,round_id,analysis_id=None):
    db.add(ReviewCommand(actor_id=actor.id,request_id=request_id,operation=operation,request_hash=hashed,
        round_id=round_id,analysis_id=analysis_id,payload=db.info.get('review_command_payload',{})));db.flush()


def context(db,round_id,actor,*,lock=False):
    initial=db.get(ReviewRound,round_id)
    if initial is None:
        raise AppError(404,'NOT_FOUND','互评轮次不存在或不可访问')
    item,assignment,version,problem=item_context(db,initial.assignment_item_id,actor,lock=lock)
    root_id=initial.root_round_id or initial.id
    if lock:
        root=db.scalar(select(ReviewRound).where(ReviewRound.id==root_id).with_for_update()
            .execution_options(populate_existing=True))
        round_=root if round_id==root_id else db.scalar(select(ReviewRound).where(ReviewRound.id==round_id)
            .with_for_update().execution_options(populate_existing=True))
    else:
        root=db.get(ReviewRound,root_id);round_=initial
    return round_,root,item,assignment,version,problem


def revision(round_,expected):
    if round_.revision_no!=expected:
        raise AppError(409,'REVIEW_VERSION_CONFLICT','互评数据已变化，请刷新后再操作')


def touch(round_):
    round_.revision_no+=1


def source(db,round_):
    snapshot=db.scalar(select(AnalysisInputSnapshot).where(AnalysisInputSnapshot.batch_id==round_.allocation_batch_id,
        AnalysisInputSnapshot.scope=='ROOT'))
    if snapshot is None or digest(snapshot.payload)!=snapshot.input_hash:
        raise AppError(409,'REVIEW_SNAPSHOT_INVALID','互评输入快照缺失或摘要不一致')
    return snapshot.payload


def root_round(db,round_):
    return db.get(ReviewRound,round_.root_round_id) if round_.root_round_id else round_
