from datetime import timezone
from sqlalchemy import select, func
from app.core.errors import AppError
from app.common.permissions import course_role, participant
from app.db.base import utcnow
from app.db.models import (User, Course, CourseMember, Assignment, AssignmentItem, ProblemVersion, Problem,
                          TestSuite, RubricItem, Submission, AnalysisJob, JudgeResult)


def iso(value):
    return value.astimezone(timezone.utc).isoformat() if value else None


def item_context(db,item_id,user):
    row=db.execute(select(AssignmentItem,Assignment,ProblemVersion,Problem)
        .join(Assignment,AssignmentItem.assignment_id==Assignment.id)
        .join(ProblemVersion,AssignmentItem.problem_version_id==ProblemVersion.id)
        .join(Problem,ProblemVersion.problem_id==Problem.id)
        .where(AssignmentItem.id==item_id)).first()
    if row is None:
        raise AppError(404,'NOT_FOUND','资源不存在或不可访问')
    item,assignment,version,problem=row
    role=course_role(db,assignment.course_id,user.id)
    if role!='TEACHER':
        participant(db,assignment.id,user.id)
        if assignment.submission_status=='DRAFT':
            raise AppError(404,'NOT_FOUND','资源不存在或不可访问')
    if problem.course_id!=assignment.course_id or version.status!='FROZEN':
        raise AppError(409,'CONFIGURATION_CONFLICT','题目版本配置尚未就绪')
    return item,assignment,version,problem,role


def item_view(db,item_id,user):
    item,a,v,p,role=item_context(db,item_id,user)
    suite=db.get(TestSuite,item.test_suite_id) if item.test_suite_id else None
    dimensions=list(db.scalars(select(RubricItem).where(RubricItem.rubric_id==item.rubric_id).order_by(RubricItem.sort_order))) if item.rubric_id else []
    return {'id':str(item.id),'assignment_id':str(a.id),'problem_code':p.code,'question_type':p.question_type,
        'title':v.title,'statement_md':v.statement_md,'answer_requirements_md':v.answer_requirements_md,
        'input_spec_md':v.input_spec_md,'output_spec_md':v.output_spec_md,'data_constraints_md':v.data_constraints_md,
        'public_examples_md':v.public_examples_md,'difficulty_level':v.difficulty_level,'version_no':v.version_no,
        'max_score':str(item.max_score),'score_weight':str(item.score_weight),'required_reviewers':item.required_reviewers,
        'submission_deadline':iso(a.submission_deadline),'review_deadline':iso(a.review_deadline),
        'submission_open':a.submission_status=='OPEN' and utcnow()<a.submission_deadline,
        'allowed_languages':suite.allowed_languages if suite else [],
        'cpu_limit_ms':suite.cpu_limit_ms if suite else None,'memory_limit_kib':suite.memory_limit_kib if suite else None,
        'rubric':[{'id':str(x.id),'name':x.name,'description':x.description,'max_score':str(x.max_score)} for x in dimensions]}


def submission_receipt(db,row,replayed=False):
    job=db.scalar(select(AnalysisJob).where(AnalysisJob.submission_id==row.id,AnalysisJob.kind=='JUDGE'))
    return {'submission_id':str(row.id),'version_no':row.version_no,'status':row.status,
            'job_status':job.status if job else 'AWAITING_REVIEW','replayed':replayed}


def accept_submission(db,item_id,user,body):
    # Serialize submissions by account: both per-item versions and cross-item idempotency use the same lock.
    db.scalar(select(User).where(User.id==user.id).with_for_update())
    item,a,v,p,role=item_context(db,item_id,user)
    if role!='STUDENT':
        raise AppError(403,'STUDENT_REQUIRED','教师账号不能提交学生答案')
    participant(db,a.id,user.id,lock=True)
    existing=db.scalar(select(Submission).where(Submission.student_id==user.id,Submission.client_request_id==body.client_request_id))
    if existing is not None:
        if existing.assignment_item_id!=item_id or existing.content!=body.content or existing.language!=body.language:
            raise AppError(409,'IDEMPOTENCY_CONFLICT','同一请求标识不能对应不同内容')
        result=submission_receipt(db,existing,True)
        db.commit()
        return result
    received=utcnow()
    if a.submission_status!='OPEN' or received>=a.submission_deadline:
        raise AppError(409,'SUBMISSION_CLOSED','作业未开放提交或已经截止')
    suite=None
    if p.question_type=='PROGRAMMING':
        suite=db.get(TestSuite,item.test_suite_id)
        if suite is None or suite.problem_version_id!=v.id or suite.status!='FROZEN':
            raise AppError(409,'CONFIGURATION_CONFLICT','测试集尚未就绪')
        if body.language not in suite.allowed_languages:
            raise AppError(422,'UNSUPPORTED_LANGUAGE','此题未配置该提交语言')
        maximum=65536
    else:
        if body.language is not None:
            raise AppError(422,'INVALID_LANGUAGE','主观题不应指定编程语言')
        maximum=262144
    if len(body.content.encode('utf-8'))>maximum:
        raise AppError(422,'CONTENT_TOO_LARGE','提交内容超过允许大小')
    latest=db.scalar(select(func.max(Submission.version_no)).where(Submission.assignment_item_id==item_id,Submission.student_id==user.id)) or 0
    row=Submission(assignment_item_id=item_id,student_id=user.id,version_no=latest+1,content=body.content,
        language=body.language,submitted_at=received,client_request_id=body.client_request_id)
    db.add(row);db.flush()
    if suite is not None:
        db.add(AnalysisJob(submission_id=row.id,parameters={'test_suite_id':str(suite.id),'problem_version_id':str(v.id)}));db.flush()
    result=submission_receipt(db,row)
    db.commit()
    return result


def visible_submission(db,sid,user):
    row=db.get(Submission,sid)
    if row is None:
        raise AppError(404,'NOT_FOUND','资源不存在或不可访问')
    item=db.get(AssignmentItem,row.assignment_item_id)
    assignment=db.get(Assignment,item.assignment_id)
    role=course_role(db,assignment.course_id,user.id)
    if role!='TEACHER':
        participant(db,assignment.id,user.id)
        if row.student_id!=user.id:
            raise AppError(404,'NOT_FOUND','资源不存在或不可访问')
    return row,assignment,role


def submission_view(db,sid,user):
    row,a,role=visible_submission(db,sid,user)
    result=db.scalar(select(JudgeResult).where(JudgeResult.submission_id==sid))
    receipt=submission_receipt(db,row)
    return {**receipt,'assignment_item_id':str(row.assignment_item_id),'student_id':str(row.student_id),
        'content':row.content,'language':row.language,'submitted_at':iso(row.submitted_at),'withdrawn_at':iso(row.withdrawn_at),
        'result':{'verdict':result.verdict,'is_mock':result.is_mock,'algorithm_name':result.algorithm_name,
                  'algorithm_version':result.algorithm_version,'cpu_time_ms':result.cpu_time_ms,'memory_kib':result.memory_kib,
                  'message':result.message} if result else None}


def withdraw_submission(db,sid,user):
    row,a,role=visible_submission(db,sid,user)
    if row.student_id!=user.id or role!='STUDENT':
        raise AppError(403,'STUDENT_REQUIRED','只能撤回本人的提交')
    db.scalar(select(Submission).where(Submission.id==sid).with_for_update())
    job=db.scalar(select(AnalysisJob).where(AnalysisJob.submission_id==sid).with_for_update())
    if row.status=='WITHDRAWN':
        result=submission_receipt(db,row,True);db.commit();return result
    if a.submission_status!='OPEN' or utcnow()>=a.submission_deadline or (job and job.status=='RUNNING'):
        raise AppError(409,'WITHDRAWAL_CLOSED','当前状态不允许撤回')
    row.status='WITHDRAWN';row.withdrawn_at=utcnow()
    if job and job.status=='PENDING':
        job.status='CANCELLED';job.finished_at=utcnow()
    db.flush();result=submission_receipt(db,row);db.commit();return result
