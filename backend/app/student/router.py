from typing import Annotated
from fastapi import APIRouter, Depends, Path, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.db.models import User,Course,CourseMember,Assignment,AssignmentItem,AssignmentParticipant,ProblemVersion,Problem
from app.common.auth import current_user
from app.common.permissions import course_role
from app.student import records
from app.student.schemas import SubmissionInput, RejudgeInput, StatusQuery
from app.student.service import item_view,accept_submission,submission_view,withdraw_submission,iso
from app.judge import results as judge_results

router=APIRouter(prefix='/api/v1',tags=['学生与公共查询'])
Id=Annotated[int,Path(gt=0,le=9223372036854775807)]
Limit=Annotated[int|None,Query(ge=1,le=100)]
Offset=Annotated[int|None,Query(ge=0)]


@router.get('/courses')
def courses(user:User=Depends(current_user),db:Session=Depends(get_db)):
    rows=db.execute(select(Course,CourseMember.role).join(CourseMember,CourseMember.course_id==Course.id)
        .where(CourseMember.user_id==user.id,CourseMember.status=='ACTIVE',Course.status=='ACTIVE').order_by(Course.id)).all()
    return {'items':[{'id':str(c.id),'name':c.name,'term':c.term,'role':role} for c,role in rows]}


@router.get('/courses/{course_id}/assignments')
def assignments(course_id:Id,user:User=Depends(current_user),db:Session=Depends(get_db)):
    role=course_role(db,course_id,user.id)
    statement=select(Assignment).where(Assignment.course_id==course_id)
    if role!='TEACHER':
        statement=statement.join(AssignmentParticipant,AssignmentParticipant.assignment_id==Assignment.id).where(
            AssignmentParticipant.student_id==user.id,Assignment.submission_status!='DRAFT')
    output=[]
    for a in db.scalars(statement.order_by(Assignment.id)):
        items=db.execute(select(AssignmentItem,ProblemVersion,Problem).join(ProblemVersion,AssignmentItem.problem_version_id==ProblemVersion.id)
            .join(Problem,ProblemVersion.problem_id==Problem.id).where(AssignmentItem.assignment_id==a.id).order_by(AssignmentItem.sort_order)).all()
        output.append({'id':str(a.id),'title':a.title,'submission_status':a.submission_status,'submission_deadline':iso(a.submission_deadline),
            'review_deadline':iso(a.review_deadline),'items':[{'id':str(i.id),'title':v.title,'question_type':p.question_type,
                'max_score':str(i.max_score),} for i,v,p in items]})
    return {'items':output}


@router.get('/courses/{course_id}/my-progress')
def my_progress(course_id:Id,user:User=Depends(current_user),db:Session=Depends(get_db),
                assignment_id:Annotated[int|None,Query(ge=1)]=None,limit:Limit=None,offset:Offset=None):
    return records.course_progress(db,course_id,user,assignment_id=assignment_id,limit=limit,offset=offset)


@router.get('/assignments/{assignment_id}')
def assignment(assignment_id:Id,user:User=Depends(current_user),db:Session=Depends(get_db)):
    return records.assignment_view(db,assignment_id,user)


@router.get('/assignment-items/{item_id}')
def item(item_id:Id,user:User=Depends(current_user),db:Session=Depends(get_db)):
    return item_view(db,item_id,user)


@router.post('/assignment-items/{item_id}/submissions',status_code=202)
def submit(item_id:Id,body:SubmissionInput,request:Request,user:User=Depends(current_user),db:Session=Depends(get_db)):
    return accept_submission(db,item_id,user,body,request)


@router.get('/me/submissions')
def my_submissions(user:User=Depends(current_user),db:Session=Depends(get_db),
                   course_id:Annotated[int|None,Query(ge=1)]=None,
                   assignment_id:Annotated[int|None,Query(ge=1)]=None,
                   assignment_item_id:Annotated[int|None,Query(ge=1)]=None,
                   language:Annotated[str|None,Query(max_length=32)]=None,
                   status:Annotated[str|None,Query(max_length=16)]=None,
                   limit:Limit=None,offset:Offset=None):
    return records.my_submissions(db,user,course_id=course_id,assignment_id=assignment_id,
                                  assignment_item_id=assignment_item_id,language=language,status=status,
                                  limit=limit,offset=offset)


@router.get('/me/judge-jobs')
def my_judge_jobs(user:User=Depends(current_user),db:Session=Depends(get_db),
                  course_id:Annotated[int|None,Query(ge=1)]=None,
                  filter:Annotated[str|None,Query(max_length=16)]=None,
                  limit:Limit=None,offset:Offset=None,
                  cursor:Annotated[str|None,Query(max_length=512)]=None):
    return records.my_judge_jobs(db,user,course_id=course_id,filter_name=filter,limit=limit,
                                 offset=offset,cursor=cursor)


@router.post('/me/judge-jobs/status')
def judge_status(body:StatusQuery,user:User=Depends(current_user),db:Session=Depends(get_db)):
    return records.batch_status(db,user,body.submission_ids)


@router.get('/submissions/{submission_id}')
def submission(submission_id:Id,user:User=Depends(current_user),db:Session=Depends(get_db)):
    return submission_view(db,submission_id,user)


@router.post('/submissions/{submission_id}/rejudge',status_code=202)
def rejudge(submission_id:Id,body:RejudgeInput,user:User=Depends(current_user),db:Session=Depends(get_db)):
    return judge_results.accept_rejudge(db,submission_id,user,body.client_request_id)


@router.post('/submissions/{submission_id}/withdraw')
def withdraw(submission_id:Id,user:User=Depends(current_user),db:Session=Depends(get_db)):
    return withdraw_submission(db,submission_id,user)
