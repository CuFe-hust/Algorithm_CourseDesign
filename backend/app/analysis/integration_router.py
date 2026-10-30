from typing import Annotated
from fastapi import APIRouter,Depends,Query,Path,Response
from pydantic import Field,StrictStr,field_validator
from sqlalchemy import select,func
from sqlalchemy.orm import Session
from app.common.auth import current_user
from app.common.permissions import require_teacher
from app.db.session import get_db
from app.db.models import User,Assignment,ReviewRound,ReviewAnalysis
from app.db.models.analytics import AnalysisBatch,AnalysisRun
from app.analysis.framework.contracts import Contract
from app.analysis.framework.catalog import PLUGINS
from app.analysis import question_results as results
from app.peer_review.router import mutate,no_store

router=APIRouter(prefix='/api/v1/analysis',tags=['模块整合与逐题结果'],dependencies=[Depends(no_store)])
Id=Annotated[int,Path(gt=0,le=9223372036854775807)]

class SnapshotCreate(Contract):
    request_id:StrictStr=Field(min_length=1,max_length=64,pattern=r'^[A-Za-z0-9_.:-]+$')
    assignment_id:StrictStr=Field(pattern=r'^[1-9][0-9]{0,18}$')
    reason:str=Field(min_length=1,max_length=2000)
    @field_validator('assignment_id')
    @classmethod
    def id_range(cls,v):
        if int(v)>9223372036854775807:raise ValueError('ID out of range')
        return v
    @field_validator('reason')
    @classmethod
    def valid_reason(cls,v):
        if not v.strip() or '\x00' in v:raise ValueError('Reason required')
        return v.strip()


class CourseSnapshotCreate(Contract):
    request_id:StrictStr=Field(min_length=1,max_length=64,pattern=r'^[A-Za-z0-9_.:-]+$')
    reason:str=Field(min_length=1,max_length=2000)
    source_batch_ids:list[Annotated[StrictStr,Field(pattern=r'^[1-9][0-9]{0,18}$')]]=Field(default_factory=list,max_length=100)
    _valid_reason=field_validator('reason')(SnapshotCreate.valid_reason.__func__)

    @field_validator('source_batch_ids')
    @classmethod
    def valid_sources(cls,values):
        if len(set(values))!=len(values) or any(int(v)>9223372036854775807 for v in values):
            raise ValueError('Invalid or duplicate source ids')
        return values


@router.post('/courses/{course_id}/course-results',status_code=201)
def course_snapshot(course_id:Id,body:CourseSnapshotCreate,db:Session=Depends(get_db),user:User=Depends(current_user)):
    from .course_results import create_snapshot
    return mutate(db,create_snapshot,course_id,user,body)


@router.get('/courses/{course_id}/student-ability/status')
def ability_status(course_id:Id,db:Session=Depends(get_db),user:User=Depends(current_user)):
    require_teacher(db,course_id,user.id)
    models=[]
    for model,pipeline in [('b0','STUDENT_ABILITY_B0'),('d1','STUDENT_ABILITY_D1')]:
        batch=db.scalar(select(AnalysisBatch).where(AnalysisBatch.course_id==course_id,
            AnalysisBatch.configuration['pipeline'].astext==pipeline,AnalysisBatch.mode=='REAL_INPUT',
            AnalysisBatch.status!='CANCELLED').order_by(AnalysisBatch.id.desc()).limit(1))
        run=db.scalar(select(AnalysisRun).where(AnalysisRun.batch_id==batch.id,AnalysisRun.step_key=='ability')) if batch else None
        models.append(dict(model=model,id=str(batch.id) if batch else None,status=run.status if run else 'NOT_GENERATED',
            business_status=run.business_status if run else None,reason=run.reason if run else {}))
    return dict(models=models)

@router.post('/courses/{course_id}/question-results',status_code=201)
def create(course_id:Id,body:SnapshotCreate,db:Session=Depends(get_db),user:User=Depends(current_user)):
    return mutate(db,results.create_snapshot,course_id,user,body)

@router.get('/courses/{course_id}/question-results/latest')
def latest(course_id:Id,assignment_id:int|None=Query(default=None,gt=0,le=9223372036854775807),limit:int=Query(default=50,ge=1,le=100),offset:int=Query(default=0,ge=0),db:Session=Depends(get_db),user:User=Depends(current_user)):
    return results.latest_view(db,course_id,user,assignment_id,limit,offset)

@router.get('/question-results/{batch_id}')
def detail(batch_id:Id,limit:int=Query(default=50,ge=1,le=100),offset:int=Query(default=0,ge=0),db:Session=Depends(get_db),user:User=Depends(current_user)):
    return results.snapshot_view(db,batch_id,user,limit,offset)

@router.get('/courses/{course_id}/workflow-status')
def status(course_id:Id,db:Session=Depends(get_db),user:User=Depends(current_user)):
    require_teacher(db,course_id,user.id)
    assignment_count=db.scalar(select(func.count()).select_from(Assignment).where(Assignment.course_id==course_id))
    round_count=db.scalar(select(func.count()).select_from(ReviewRound).where(ReviewRound.course_id==course_id))
    versions=db.scalar(select(func.count()).select_from(ReviewAnalysis).join(ReviewRound,ReviewRound.id==ReviewAnalysis.root_round_id).where(ReviewRound.course_id==course_id))
    snapshots=db.scalar(select(func.count()).select_from(AnalysisBatch).where(AnalysisBatch.course_id==course_id,AnalysisBatch.configuration['pipeline'].astext==results.PIPELINE))
    missing=[dict(key=k,label='旧版能力插件（已另接B0/D1）' if k=='ability' else p.label) for k,p in PLUGINS.items() if p.implementation=='not_implemented']
    chains=[dict(number=1,title='编程评测',state='READY',description='复用评测队列与真实执行上下文，保留测试证据。',href='/teacher/assignments'),
        dict(number=2,title='内容证据',state='PARTIAL',description='代码相似与证据查看已接入；文本与AI辅助信号仍待实现。',href='/teacher/similarity'),
        dict(number=3,title='主观互评',state='READY',description='冻结作品、确认分配、匿名评分与原始评价。',href='/teacher/reviews'),
        dict(number=4,title='聚合与异常',state='READY',description='四类检测、教师复核、补评与版本重算。',href='/teacher/reviews'),
        dict(number=5,title='逐题结果',state='READY',description='固定编程与主观候选来源，不计算作业总分。',href='/teacher/results'),
        dict(number=6,title='学习分析',state='PARTIAL',description='B0章节表现、D1难度感知模型与学生个人面板已接通；旧知识掌握、经验难度插件仍为占位。',href='/teacher/results')]
    return dict(chains=chains,unimplemented=missing,counts=dict(assignments=assignment_count,review_rounds=round_count,analysis_versions=versions,result_snapshots=snapshots))
