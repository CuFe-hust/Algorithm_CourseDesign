from sqlalchemy import select
from sqlalchemy.orm import Session
from app.db.base import utcnow
from app.db.models import (Course,Assignment,AssignmentItem,AssignmentParticipant,CourseMember,User,
    Submission,ProblemVersion,Problem,JudgeResult)
from app.judge.config import execution_mode,runtime_profile
from app.judge.selection import Candidate,choose_best
from app.core.errors import AppError
from .fixtures import demo_snapshot


def capture(db,course_id,assignment_id,mode,seed):
    # An independent repeatable-read transaction prevents mixed generations after
    # authentication queries have already begun the request transaction.
    with Session(db.bind.execution_options(isolation_level='REPEATABLE READ')) as source:
        if source.get(Course,course_id) is None:raise AppError(404,'NOT_FOUND','课程不可访问')
        if assignment_id is not None:
            assignment=source.get(Assignment,assignment_id)
            if assignment is None or assignment.course_id!=course_id:
                raise AppError(404,'NOT_FOUND','作业不可访问')
        if mode=='DEMO':return demo_snapshot(seed)
        if mode!='REAL_INPUT':raise ValueError('Unsupported mode')
        return _capture(source,course_id,assignment_id)


def _capture(db,course_id,assignment_id):
    now=utcnow()
    assignments=list(db.scalars(select(Assignment).where(Assignment.course_id==course_id,
        Assignment.submission_status!='DRAFT',*([Assignment.id==assignment_id] if assignment_id else []))))
    assignment_map={a.id:a for a in assignments}
    members=list(db.execute(select(CourseMember.user_id,User.status).join(User).where(
        CourseMember.course_id==course_id,CourseMember.role=='STUDENT',CourseMember.status=='ACTIVE')))
    if len(members)>2000:raise AppError(422,'ANALYSIS_SCOPE_TOO_LARGE','请缩小分析范围')
    participants=list(db.scalars(select(AssignmentParticipant).where(AssignmentParticipant.assignment_id.in_(assignment_map)))) if assignments else []
    roster_ids={p.student_id for p in participants} if assignment_id else {uid for uid,_ in members}
    key=lambda value:f'student-{value}'
    roster=sorted(key(u) for u in roster_ids)
    reviewers=sorted(key(uid) for uid,status in members if status=='ACTIVE' and uid in roster_ids)
    rows=list(db.execute(select(AssignmentItem,ProblemVersion,Problem).join(ProblemVersion,
        ProblemVersion.id==AssignmentItem.problem_version_id).join(Problem,Problem.id==ProblemVersion.problem_id)
        .where(AssignmentItem.assignment_id.in_(assignment_map)))) if assignments else []
    item_map={i.id:(i,v,p) for i,v,p in rows}
    submissions=list(db.scalars(select(Submission).where(Submission.assignment_item_id.in_(item_map),
        Submission.status=='SUBMITTED').order_by(Submission.submitted_at,Submission.id))) if rows else []
    result_rows=list(db.scalars(select(JudgeResult).where(JudgeResult.submission_id.in_([s.id for s in submissions])))) if submissions else []
    results={r.submission_id:r for r in result_rows}
    mode=execution_mode();profile=runtime_profile(mode)
    grouped={};events=[]
    for submission in submissions:
        assignment=assignment_map[item_map[submission.assignment_item_id][0].assignment_id]
        if submission.student_id not in roster_ids:continue
        events.append(dict(student_key=key(submission.student_id),kind='SUBMITTED',occurred_at=submission.submitted_at.isoformat()))
        if submission.submitted_at>=assignment.submission_deadline:continue
        grouped.setdefault((submission.assignment_item_id,submission.student_id),[]).append(submission)
    answers=[];code=[];judge=[];scopes=[];selected=[]
    for item,version,problem in rows:
        assignment=assignment_map[item.assignment_id]
        # Course-wide batches retain item boundaries rather than comparing unrelated questions.
        scopes.append(dict(item_key=f'item-{item.id}',question_type=problem.question_type,
            problem_version_id=str(version.id),rubric_id=str(item.rubric_id) if item.rubric_id else None,
            test_suite_id=str(item.test_suite_id) if item.test_suite_id else None,
            required_reviewers=item.required_reviewers,submission_deadline=assignment.submission_deadline.isoformat(),
            assignment_updated_at=assignment.updated_at.isoformat(),closed=assignment.submission_status=='CLOSED' and assignment.submission_deadline<=now))
        for uid in sorted(roster_ids):
            history=grouped.get((item.id,uid),[])
            if not history:continue
            if problem.question_type=='PROGRAMMING':
                # Similarity uses the final submission, not a mixture of different questions.
                chosen=history[-1];code.append(dict(answer_key=f'submission-{chosen.id}',author_key=key(uid),
                    content=chosen.content,language=chosen.language,item_key=f'item-{item.id}'))
                eligible=[s for s in history if s.id in results and not results[s.id].is_mock
                    and results[s.id].execution_mode==mode and results[s.id].runtime_profile==profile
                    and results[s.id].passed_cases is not None]
                winner=choose_best([Candidate(s.id,s.version_no,s.submitted_at,results[s.id].passed_cases,
                    results[s.id].cpu_time_ms,results[s.id].memory_kib) for s in eligible])
                if winner:
                    r=results[winner.submission_id]
                    judge.append(dict(student_key=key(uid),submission_key=f'submission-{winner.submission_id}',
                        passed_cases=r.passed_cases,total_cases=r.total_cases,verdict=r.verdict,
                        execution_mode=r.execution_mode,runtime_profile=r.runtime_profile,is_mock=r.is_mock))
            else:
                chosen=history[-1];answers.append(dict(answer_key=f'submission-{chosen.id}',author_key=key(uid),
                    content=chosen.content,language=None,item_key=f'item-{item.id}'))
            selected.append(str(chosen.id))
    # REAL_INPUT batch-level algorithms intentionally wait for explicit item selection.
    # Never compare answers from different items in one similarity/matching task.
    return dict(schema_version='analysis-v1',is_mock=False,roster=roster,reviewers=reviewers,answers=answers,code=code,
        rubric_max=None,required_reviewers=None,reference_scores={},judge_results=judge,evaluations=None,grades=None,
        events=events,available_event_types=['SUBMITTED'],time_range={'to':now.isoformat()},
        test_suite_key=None,evaluation_context={'execution_mode':mode,'runtime_profile':profile},
        submitted=sorted({e['student_key'] for e in events}),scopes=scopes,
        source_versions={'captured_at':now.isoformat(),'selected_submission_ids':selected,
            'assignment_ids':[str(a.id) for a in assignments]})
