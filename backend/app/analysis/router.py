"""Teacher-only analysis framework. No public arbitrary artifact access."""
from typing import Literal
from fastapi import APIRouter,Depends
from pydantic import Field,StrictStr,field_validator
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.common.auth import current_user
from app.core.errors import AppError
from app.db.models import User
from app.db.session import get_db
from app.student.router import Id
from .framework.contracts import Contract
from .framework.catalog import catalogue
from .framework import service

router=APIRouter(prefix='/api/v1/analysis',tags=['分析框架'])


class Request(Contract):
    request_id:StrictStr=Field(min_length=1,max_length=64,pattern=r'^[A-Za-z0-9_.:-]+$')


class BatchCreate(Request):
    mode:Literal['DEMO','REAL_INPUT']='DEMO'
    seed:int=Field(default=20261026,strict=True,ge=-2147483648,le=2147483647)
    assignment_id:StrictStr|None=Field(default=None,pattern=r'^[1-9][0-9]{0,18}$')
    assignment_item_id:StrictStr|None=Field(default=None,pattern=r'^[1-9][0-9]{0,18}$')

    @field_validator('assignment_id','assignment_item_id')
    @classmethod
    def valid_id(cls,value):
        if value is not None and int(value)>9223372036854775807:
            raise ValueError('ID exceeds signed 64-bit range')
        return value


class DemoEvent(Request):
    event:Literal['OPEN_REVIEW','SUBMIT_REVIEWS','RESOLVE','SUBMIT_SUPPLEMENT']
    expected_version:int=Field(ge=0,strict=True)
    action:Literal['KEEP','SUPPLEMENT']='KEEP'


class AbilityBatchCreate(Request):
    mode:Literal['DEMO','REAL_INPUT']='DEMO'
    seed:int=Field(default=20261026,strict=True,ge=-2147483648,le=2147483647)
    source_batch_id:StrictStr|None=Field(default=None,pattern=r'^[1-9][0-9]{0,18}$')
    _valid_source_id=field_validator('source_batch_id')(BatchCreate.valid_id.__func__)


def write(db,fn,*args):
    try:return fn(db,*args)
    except IntegrityError:
        db.rollback();raise AppError(409,'WRITE_CONFLICT','分析数据已变化，请重新读取或重试同一请求')
    except Exception:
        db.rollback();raise


@router.get('/catalog')
def catalog(user:User=Depends(current_user)):
    return {'schema_version':'analysis-v2','items':catalogue()}


@router.post('/courses/{course_id}/batches',status_code=201)
def create(course_id:Id,body:BatchCreate,user:User=Depends(current_user),db:Session=Depends(get_db)):
    return write(db,service.create_batch,course_id,user,body.model_dump())


@router.get('/batches/{batch_id}')
def detail(batch_id:Id,user:User=Depends(current_user),db:Session=Depends(get_db)):
    return service.batch_view(db,batch_id,user)


@router.post('/courses/{course_id}/student-ability/batches',status_code=201)
def create_ability(course_id:Id,body:AbilityBatchCreate,user:User=Depends(current_user),db:Session=Depends(get_db)):
    return write(db,service.create_ability_batch,course_id,user,body.model_dump())


@router.get('/batches/{batch_id}/input')
def ability_input(batch_id:Id,user:User=Depends(current_user),db:Session=Depends(get_db)):
    return service.ability_input_view(db,batch_id,user)


@router.post('/batches/{batch_id}/run')
def run(batch_id:Id,body:Request,user:User=Depends(current_user),db:Session=Depends(get_db)):
    return write(db,service.advance,batch_id,user,body.request_id)


@router.post('/batches/{batch_id}/demo-events')
def event(batch_id:Id,body:DemoEvent,user:User=Depends(current_user),db:Session=Depends(get_db)):
    return write(db,service.demo_event,batch_id,user,body.model_dump())


@router.post('/batches/{batch_id}/runs/{run_id}/retry')
def retry(batch_id:Id,run_id:Id,body:Request,user:User=Depends(current_user),db:Session=Depends(get_db)):
    return write(db,service.retry_run,batch_id,run_id,user,body.request_id)
