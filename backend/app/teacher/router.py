from fastapi import APIRouter,Depends,Query
from sqlalchemy import select,func
from sqlalchemy.orm import Session
from app.db.models import User,Submission,AssignmentItem,Assignment
from app.db.session import get_db
from app.common.auth import current_user
from app.common.permissions import require_teacher
from app.student.router import Id
from app.student.service import iso

router=APIRouter(prefix='/api/v1/teacher',tags=['教师查询'])


@router.get('/courses/{course_id}/submissions')
def submissions(course_id:Id,user:User=Depends(current_user),db:Session=Depends(get_db),
                assignment_item_id:int|None=Query(default=None,gt=0,le=9223372036854775807),
                student_id:int|None=Query(default=None,gt=0,le=9223372036854775807),
                limit:int=Query(default=20,ge=1,le=100),offset:int=Query(default=0,ge=0)):
    require_teacher(db,course_id,user.id)
    query=select(Submission).join(AssignmentItem,Submission.assignment_item_id==AssignmentItem.id)
    query=query.join(Assignment,AssignmentItem.assignment_id==Assignment.id).where(Assignment.course_id==course_id)
    if assignment_item_id is not None:query=query.where(Submission.assignment_item_id==assignment_item_id)
    if student_id is not None:query=query.where(Submission.student_id==student_id)
    total=db.scalar(select(func.count()).select_from(query.subquery()))
    rows=db.scalars(query.order_by(Submission.id.desc()).limit(limit).offset(offset))
    return {'total':total,'limit':limit,'offset':offset,'items':[{'submission_id':str(s.id),'student_id':str(s.student_id),
        'assignment_item_id':str(s.assignment_item_id),'version_no':s.version_no,'status':s.status,'submitted_at':iso(s.submitted_at)} for s in rows]}
