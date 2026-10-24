from datetime import timezone
from sqlalchemy import select, func
from app.core import limits, ratelimit
from app.core.errors import AppError
from app.common.permissions import course_role, participant
from app.db.base import utcnow
from app.db.models import (User, Assignment, AssignmentItem, ProblemVersion, Problem,
                          TestSuite, TestCase, RubricItem, Submission, AnalysisJob, JudgeResult)
from app.judge import config as judge_config
from app.judge import locks
from app.judge import results as judge_results


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


def public_test_cases(db,item):
    if not item.test_suite_id:
        return []
    if db.scalar(select(TestSuite.id).where(TestSuite.id==item.test_suite_id)) is None:
        return []
    rows=list(db.scalars(select(TestCase).where(TestCase.test_suite_id==item.test_suite_id,
                                                TestCase.is_public.is_(True)).order_by(TestCase.sort_order)))
    cases=[{'case_no':n,'input_text':case.input_text,'expected_output':case.expected_output}
           for n,case in enumerate(rows,1)]
    return cases


def item_view(db,item_id,user):
    item,a,v,p,role=item_context(db,item_id,user)
    suite=db.get(TestSuite,item.test_suite_id) if item.test_suite_id else None
    dimensions=list(db.scalars(select(RubricItem).where(RubricItem.rubric_id==item.rubric_id).order_by(RubricItem.sort_order))) if item.rubric_id else []
    return {'id':str(item.id),'assignment_id':str(a.id),'problem_code':p.code,'question_type':p.question_type,
        'title':v.title,'statement_md':v.statement_md,'answer_requirements_md':v.answer_requirements_md,
        'input_spec_md':v.input_spec_md,'output_spec_md':v.output_spec_md,'data_constraints_md':v.data_constraints_md,
        'public_examples_md':v.public_examples_md,'difficulty_level':v.difficulty_level,'version_no':v.version_no,
        'problem_version_id':str(v.id),'server_time':utcnow().isoformat(),
        'max_score':str(item.max_score),'score_weight':str(item.score_weight),'required_reviewers':item.required_reviewers,
        'submission_deadline':iso(a.submission_deadline),'review_deadline':iso(a.review_deadline),
        'submission_open':a.submission_status=='OPEN' and utcnow()<a.submission_deadline,
        'allowed_languages':suite.allowed_languages if suite else [],
        'cpu_limit_ms':suite.cpu_limit_ms if suite else None,'memory_limit_kib':suite.memory_limit_kib if suite else None,
        'public_test_cases':public_test_cases(db,item),
        'rubric':[{'id':str(x.id),'name':x.name,'description':x.description,'max_score':str(x.max_score)} for x in dimensions]}


def submission_receipt(db,row,replayed=False):
    job=db.scalar(select(AnalysisJob).where(AnalysisJob.submission_id==row.id,AnalysisJob.kind=='JUDGE')
                  .execution_options(populate_existing=True))
    return {'submission_id':str(row.id),'version_no':row.version_no,'status':row.status,
            'job_status':job.status if job else 'AWAITING_REVIEW','replayed':replayed}


def _existing(db,user_id,client_request_id):
    return db.scalar(select(Submission).where(Submission.student_id==user_id,
                                              Submission.client_request_id==client_request_id))


def _replay(db,existing,item_id,body):
    if existing.assignment_item_id!=item_id or existing.content!=body.content or existing.language!=body.language:
        raise AppError(409,'IDEMPOTENCY_CONFLICT','同一请求标识不能对应不同内容')
    result=submission_receipt(db,existing,True)
    db.commit()
    return result


def _guard_capacity(db,user_id):
    """Backlog is checked inside the shared intake lock so the decision and the insert are atomic."""
    personal=db.scalar(select(func.count()).select_from(AnalysisJob)
        .join(Submission,Submission.id==AnalysisJob.submission_id)
        .where(Submission.student_id==user_id,AnalysisJob.kind=='JUDGE',
               AnalysisJob.status.in_(['PENDING','RUNNING']))) or 0
    if personal>=limits.personal_backlog_limit():
        db.commit()
        raise AppError(429,'SUBMISSION_BACKLOG_LIMIT','本人待处理评测过多，请稍后再提交',
                       {'personal_backlog':personal,'limit':limits.personal_backlog_limit()},
                       headers={'Retry-After':'60'})
    node=db.scalar(select(func.count()).select_from(AnalysisJob).where(
        AnalysisJob.kind=='JUDGE',AnalysisJob.status=='PENDING')) or 0
    if node>=limits.node_backlog_limit():
        db.commit()
        raise AppError(503,'JUDGE_BACKLOG_FULL','评测队列已满，请稍后重试',
                       {'node_backlog':node,'limit':limits.node_backlog_limit()},
                       headers={'Retry-After':'120'})


def _mode_parameters(suite,version):
    mode=judge_config.execution_mode()
    return {'test_suite_id':str(suite.id),'problem_version_id':str(version.id),
            'execution_mode':mode,'runtime_profile':judge_config.runtime_profile(mode)}


def _check_programming_config(suite,version,language):
    mode=judge_config.execution_mode()
    if not judge_config.driver_available(mode):
        raise AppError(409,'JUDGE_CONFIGURATION_UNSUPPORTED','当前评测环境尚未接入，请联系课程管理员')
    if suite is None or suite.problem_version_id!=version.id or suite.status!='FROZEN':
        raise AppError(409,'CONFIGURATION_CONFLICT','测试集尚未就绪')
    if language not in suite.allowed_languages:
        raise AppError(422,'UNSUPPORTED_LANGUAGE','此题未配置该提交语言')
    if mode==judge_config.LOCAL and judge_config.toolchain(language) is None:
        # Permanent configuration fault: never queue a job that can never be claimed.
        raise AppError(409,'JUDGE_CONFIGURATION_UNSUPPORTED','当前评测节点不支持该语言，请联系课程管理员')


def accept_submission(db,item_id,user,body,request=None):
    replay=_existing(db,user.id,body.client_request_id)
    if replay is not None:
        return _replay(db,replay,item_id,body)
    key=ratelimit.subject_key(str(user.id))
    ratelimit.enforce(db,'submission_minute',key,limits.submission_per_minute(),60,
                      message='提交过于频繁，请稍后再试')
    ratelimit.enforce(db,'submission_burst',key,limits.submission_burst(),
                      limits.submission_burst_window_seconds(),message='提交过于频繁，请稍后再试')
    db.commit()

    # Global intake lock: backlog snapshot and enqueue are one atomic decision.
    locks.xact_lock(db,locks.INTAKE)
    _guard_capacity(db,user.id)
    db.scalar(select(User).where(User.id==user.id).with_for_update())
    item,a,v,p,role=item_context(db,item_id,user)
    if role!='STUDENT':
        raise AppError(403,'STUDENT_REQUIRED','教师账号不能提交学生答案')
    participant(db,a.id,user.id,lock=True)
    existing=_existing(db,user.id,body.client_request_id)
    if existing is not None:
        return _replay(db,existing,item_id,body)
    received=utcnow()
    if a.submission_status!='OPEN' or received>=a.submission_deadline:
        raise AppError(409,'SUBMISSION_CLOSED','作业未开放提交或已经截止')
    suite=None
    if p.question_type=='PROGRAMMING':
        suite=db.get(TestSuite,item.test_suite_id)
        _check_programming_config(suite,v,body.language)
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
        db.add(AnalysisJob(submission_id=row.id,parameters=_mode_parameters(suite,v)));db.flush()
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
    job=db.scalar(select(AnalysisJob).where(AnalysisJob.submission_id==sid,AnalysisJob.kind=='JUDGE')
                  .execution_options(populate_existing=True))
    result=db.scalar(select(JudgeResult).where(JudgeResult.submission_id==sid)
                     .execution_options(populate_existing=True))
    receipt=submission_receipt(db,row)
    job_payload=judge_results.job_view(job)
    if job_payload is not None:
        can_retry,block_reason,retry_after=judge_results.retry_state(db,job)
        job_payload.update({'can_retry':can_retry,'retry_block_reason':block_reason,
                            'retry_after_at':iso(retry_after)})
    return {**receipt,'assignment_item_id':str(row.assignment_item_id),'assignment_id':str(a.id),
        'course_id':str(a.course_id),'student_id':str(row.student_id),
        'content':row.content,'language':row.language,'submitted_at':iso(row.submitted_at),'withdrawn_at':iso(row.withdrawn_at),
        'job':job_payload,'result':judge_results.result_view(result)}


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
        job.status='CANCELLED';job.finished_at=utcnow();job.phase='FINISHED'
    db.flush();result=submission_receipt(db,row);db.commit();return result
