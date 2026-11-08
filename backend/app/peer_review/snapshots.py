"""Frozen business facts and purpose-scoped anonymous algorithm projections."""
from decimal import Decimal
import hashlib
import hmac

from sqlalchemy import select
from sqlalchemy.orm import Session
from app.common.permissions import require_teacher
from app.core.config import Settings
from app.core.errors import AppError
from app.db.base import utcnow
from app.db.models import (Assignment, AssignmentItem, AssignmentParticipant, CourseMember, User,
    Problem, ProblemVersion, Rubric, RubricItem, Submission)
from app.analysis.framework.contracts import digest
from app.student.service import iso

MAX_PEOPLE = 300


def anonymous(course_id, kind, value):
    raw=f'peer-review-v1:{course_id}:{kind}:{value}'.encode()
    return kind+'_'+hmac.new(Settings.load().secret.encode(),raw,hashlib.sha256).hexdigest()[:40]


def item_context(db, item_id, actor, *, lock=False):
    item=db.get(AssignmentItem,item_id)
    assignment=db.get(Assignment,item.assignment_id) if item else None
    if assignment is None:
        raise AppError(404,'NOT_FOUND','题目不存在或不可访问')
    require_teacher(db,assignment.course_id,actor.id)
    if lock:
        assignment=db.scalar(select(Assignment).where(Assignment.id==assignment.id).with_for_update()
            .execution_options(populate_existing=True))
    version=db.get(ProblemVersion,item.problem_version_id)
    problem=db.get(Problem,version.problem_id)
    if problem.course_id!=assignment.course_id or problem.question_type=='PROGRAMMING' or not item.rubric_id:
        raise AppError(422,'SUBJECTIVE_ITEM_REQUIRED','请选择本课程的主观题')
    if version.status!='FROZEN':
        raise AppError(409,'FROZEN_VERSION_REQUIRED','互评必须使用已冻结的题目版本')
    return item,assignment,version,problem


def capture(db,item,assignment,version,problem):
    # The caller holds the assignment lock; one MVCC snapshot freezes membership and answers together.
    with Session(db.get_bind().execution_options(isolation_level="REPEATABLE READ")) as frozen:
        return _capture(frozen,frozen.get(AssignmentItem,item.id),frozen.get(Assignment,assignment.id),
            frozen.get(ProblemVersion,version.id),frozen.get(Problem,problem.id))


def _capture(db,item,assignment,version,problem):
    if assignment.submission_status!='CLOSED' or assignment.submission_deadline>utcnow():
        raise AppError(409,'SUBMISSIONS_NOT_FROZEN','请先关闭提交，并等待提交截止到达后再创建互评')
    rubric=db.get(Rubric,item.rubric_id)
    dimensions=list(db.scalars(select(RubricItem).where(RubricItem.rubric_id==item.rubric_id).order_by(RubricItem.sort_order)))
    if (rubric is None or rubric.problem_version_id!=version.id or rubric.status!='FROZEN' or not dimensions
            or any(not d.description.strip() or d.max_score<=0 for d in dimensions)):
        raise AppError(409,'INVALID_RUBRIC','题目量表不完整或不属于冻结题目版本')
    participants=list(db.scalars(select(AssignmentParticipant).where(AssignmentParticipant.assignment_id==assignment.id)
        .order_by(AssignmentParticipant.student_id)))
    if len(participants)>MAX_PEOPLE:
        raise AppError(422,'REVIEW_SCOPE_TOO_LARGE','单题互评最多支持300位应交学生，请拆分教学范围')
    ids=[p.student_id for p in participants]
    members={m.user_id:m for m in db.scalars(select(CourseMember).where(
        CourseMember.course_id==assignment.course_id,CourseMember.user_id.in_(ids)))}
    users={u.id:u for u in db.scalars(select(User).where(User.id.in_(ids)))}
    roster=[{'student_id':str(p.student_id),'class_id_at_publish':str(p.class_id_at_publish),
        'class_name_at_publish':p.class_name_at_publish,'account_status':users[p.student_id].status,
        'member_status':members[p.student_id].status if p.student_id in members else None,
        'member_role':members[p.student_id].role if p.student_id in members else None} for p in participants]
    reviewer_ids=[p.student_id for p in participants if users[p.student_id].status=='ACTIVE'
        and p.student_id in members and members[p.student_id].status=='ACTIVE' and members[p.student_id].role=='STUDENT']
    rows=list(db.scalars(select(Submission).where(Submission.assignment_item_id==item.id,
        Submission.student_id.in_(ids),Submission.status=='SUBMITTED',Submission.submitted_at<assignment.submission_deadline)
        .order_by(Submission.submitted_at,Submission.version_no,Submission.id)))
    latest={s.student_id:s for s in rows}
    facts=dict(assignment_item_id=str(item.id),assignment_id=str(assignment.id),assignment_title=assignment.title,course_id=str(assignment.course_id),
        problem_version_id=str(version.id),rubric_id=str(rubric.id),question_type=problem.question_type,
        required_reviewers=item.required_reviewers,item_max_score=str(item.max_score),
        submission_deadline=iso(assignment.submission_deadline),submission_status=assignment.submission_status,
        question={'title':version.title,'statement_md':version.statement_md,'answer_requirements_md':version.answer_requirements_md},
        rubric=[{'id':str(d.id),'name':d.name,'description':d.description,'max_score':str(d.max_score)} for d in dimensions],
        rubric_max=str(sum((d.max_score for d in dimensions),Decimal(0))),roster=roster,
        reviewer_ids=[str(i) for i in reviewer_ids],
        answers=[{'submission_id':str(s.id),'student_id':str(s.student_id),'version_no':s.version_no,
            'submitted_at':iso(s.submitted_at),'content':s.content} for s in sorted(latest.values(),key=lambda s:s.student_id)])
    if len(str(facts).encode())>8*1024*1024:
        raise AppError(422,'REVIEW_SCOPE_TOO_LARGE','互评答案快照超过8MiB，请缩小范围')
    return facts


def project(facts):
    course=facts['course_id']
    identities={r['student_id']:anonymous(course,'u',r['student_id']) for r in facts['roster']}
    answers=[dict(answer_key=anonymous(course,'a',a['submission_id']),author_key=identities[a['student_id']],
        **{k:v for k,v in a.items() if k!='content'}) for a in facts['answers']]
    return {'facts':facts,'answers':answers,'identities':identities,
        'reviewers':[identities[i] for i in facts['reviewer_ids']], 'is_mock':False,
        'schema_version':'peer-review-v1','source_facts_hash':digest(facts)}
