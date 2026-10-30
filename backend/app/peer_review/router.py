from typing import Annotated
from fastapi import APIRouter,Depends,Path,Query,Response
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from app.common.auth import current_user
from app.db.session import get_db
from app.db.models import User,ReviewAnalysis,ReviewTask
from app.core.errors import AppError
from . import schemas as s,rounds,analyses,queries,core,evaluations

def no_store(response:Response):
    response.headers['Cache-Control']='no-store'

router=APIRouter(prefix='/api/v1/peer-review',tags=['真实主观互评与复核'],dependencies=[Depends(no_store)])
Id=Annotated[int,Path(gt=0,le=9223372036854775807)]
Limit=Annotated[int,Query(ge=1,le=100)]
Offset=Annotated[int,Query(ge=0)]

@router.get('/teacher/courses/{course_id}/rounds')
def listing(course_id:Id,db:Session=Depends(get_db),user:User=Depends(current_user),limit:Limit=20,offset:Offset=0):
    return queries.list_rounds(db,course_id,user,limit,offset)

@router.get('/teacher/assignment-items/{item_id}/options')
def options(item_id:Id,db:Session=Depends(get_db),user:User=Depends(current_user)):
    return queries.options(db,item_id,user)

@router.get('/teacher/rounds/{round_id}')
def view(round_id:Id,db:Session=Depends(get_db),user:User=Depends(current_user)):
    core.context(db,round_id,user);return queries.round_view(db,round_id)

@router.get('/teacher/rounds/{round_id}/tasks')
def tasks(round_id:Id,db:Session=Depends(get_db),user:User=Depends(current_user),limit:Limit=20,offset:Offset=0):
    return queries.task_rows(db,round_id,user,limit,offset)

@router.get('/teacher/tasks/{task_id}')
def teacher_task(task_id:Id,db:Session=Depends(get_db),user:User=Depends(current_user)):
    t=db.get(ReviewTask,task_id)
    if t is None:raise AppError(404,'NOT_FOUND','任务不存在')
    r,*_=core.context(db,t.round_id,user)
    return evaluations.detail(db,t,r)

@router.get('/teacher/analyses/{analysis_id}')
def analysis(analysis_id:Id,db:Session=Depends(get_db),user:User=Depends(current_user)):
    a=db.get(ReviewAnalysis,analysis_id)
    if a is None:raise AppError(404,'NOT_FOUND','分析不存在')
    core.context(db,a.root_round_id,user);return queries.analysis_view(db,a)

@router.get('/teacher/rounds/{round_id}/results')
def results(round_id:Id,db:Session=Depends(get_db),user:User=Depends(current_user)):
    _,root,*_=core.context(db,round_id,user);return analyses.handoff(db,root)


def mutate(db,fn,*args):
    try:
        result=fn(db,*args);db.commit();return result
    except IntegrityError:
        db.rollback();raise AppError(409,'REVIEW_WRITE_CONFLICT','互评数据发生并发冲突，请刷新后重试')

@router.post('/teacher/assignment-items/{item_id}/previews',status_code=201)
def preview(item_id:Id,body:s.Preview,db:Session=Depends(get_db),user:User=Depends(current_user)):
    return mutate(db,rounds.create_preview,item_id,user,body)

@router.post('/teacher/rounds/{round_id}/publish')
def publish(round_id:Id,body:s.Publish,db:Session=Depends(get_db),user:User=Depends(current_user)):
    return mutate(db,rounds.publish,round_id,user,body)

@router.post('/teacher/rounds/{round_id}/cancel')
def cancel(round_id:Id,body:s.ReasonCommand,db:Session=Depends(get_db),user:User=Depends(current_user)):
    return mutate(db,rounds.cancel,round_id,user,body)

@router.post('/teacher/rounds/{round_id}/deadline')
def deadline(round_id:Id,body:s.Deadline,db:Session=Depends(get_db),user:User=Depends(current_user)):
    return mutate(db,rounds.extend,round_id,user,body)

@router.post('/teacher/rounds/{round_id}/close')
def close(round_id:Id,body:s.Close,db:Session=Depends(get_db),user:User=Depends(current_user)):
    return mutate(db,rounds.close,round_id,user,body)

@router.post('/teacher/rounds/{round_id}/analyses')
def reanalyze(round_id:Id,body:s.ReasonCommand,db:Session=Depends(get_db),user:User=Depends(current_user)):
    return mutate(db,analyses.reanalyze,round_id,user,body)

@router.post('/teacher/analyses/{analysis_id}/resolve')
def resolve(analysis_id:Id,body:s.Resolve,db:Session=Depends(get_db),user:User=Depends(current_user)):
    return mutate(db,analyses.resolve,analysis_id,user,body)

@router.get('/courses/{course_id}/my-tasks')
def mine(course_id:Id,db:Session=Depends(get_db),user:User=Depends(current_user),limit:Limit=20,offset:Offset=0):
    return queries.student_tasks(db,course_id,user,limit,offset)

@router.get('/tasks/{task_id}')
def open_task(task_id:Id,response:Response,db:Session=Depends(get_db),user:User=Depends(current_user)):
    response.headers['Cache-Control']='no-store'
    return mutate(db,evaluations.open_task,task_id,user)

@router.post('/tasks/{task_id}/evaluation')
def evaluate(task_id:Id,body:s.EvaluationInput,db:Session=Depends(get_db),user:User=Depends(current_user)):
    return mutate(db,evaluations.submit,task_id,user,body)
