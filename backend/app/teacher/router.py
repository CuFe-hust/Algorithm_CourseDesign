from contextlib import contextmanager
import logging

from fastapi import APIRouter,Depends,Query,File,Form,UploadFile,Response
from sqlalchemy import select,func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.db.models import (User,Submission,AssignmentItem,Assignment,Problem,ProblemVersion,
                           KnowledgePoint,CourseMember,StudentProfile)
from app.db.session import get_db
from app.common.auth import current_user
from app.common.permissions import require_teacher
from app.student.router import Id
from app.student.service import iso
from app.core.errors import AppError
from app.teacher import problems as problem_service, students as student_service
from app.teacher.schemas import (ProblemCreate,VersionUpdate,VersionAction,VersionFork,
                                 KnowledgeCreate,QuestionType)

router=APIRouter(prefix='/api/v1/teacher',tags=['教师管理'])
logger=logging.getLogger(__name__)


@contextmanager
def write_transaction(db):
    try:
        yield
        db.commit()
    except IntegrityError:
        db.rollback()
        raise AppError(409,'WRITE_CONFLICT','数据与现有记录发生冲突，请刷新或重新预览后再试')
    except Exception:
        db.rollback()
        raise


@router.get('/courses/{course_id}/overview')
def overview(course_id:Id,user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_teacher(db,course_id,user.id)
    types=dict(db.execute(select(Problem.question_type,func.count()).where(
        Problem.course_id==course_id,Problem.status=='ACTIVE').group_by(Problem.question_type)).all())
    student_query=select(User.status,func.count()).join(CourseMember,CourseMember.user_id==User.id).where(
        CourseMember.course_id==course_id,CourseMember.role=='STUDENT',CourseMember.status=='ACTIVE').group_by(User.status)
    students_by_status=dict(db.execute(student_query).all())
    classes=db.scalar(select(func.count(func.distinct(StudentProfile.class_id))).join(
        CourseMember,CourseMember.user_id==StudentProfile.user_id).where(CourseMember.course_id==course_id,
        CourseMember.role=='STUDENT',CourseMember.status=='ACTIVE'))
    drafts=db.scalar(select(func.count()).select_from(ProblemVersion).join(Problem,Problem.id==ProblemVersion.problem_id)
                     .where(Problem.course_id==course_id,Problem.status=='ACTIVE',ProblemVersion.status=='DRAFT'))
    return {'problems':sum(types.values()),'problems_by_type':types,'drafts':drafts,
            'students':sum(students_by_status.values()),'students_by_status':students_by_status,'classes':classes}


@router.get('/courses/{course_id}/knowledge-points')
def knowledge_points(course_id:Id,user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_teacher(db,course_id,user.id)
    rows=db.scalars(select(KnowledgePoint).where(KnowledgePoint.course_id==course_id,
                    KnowledgePoint.status=='ACTIVE').order_by(KnowledgePoint.name,KnowledgePoint.id))
    return {'items':[{'id':str(k.id),'name':k.name,'code':k.code} for k in rows]}


@router.post('/courses/{course_id}/knowledge-points',status_code=201)
def create_knowledge_point(course_id:Id,body:KnowledgeCreate,user:User=Depends(current_user),db:Session=Depends(get_db)):
    with write_transaction(db):
        return problem_service.create_knowledge(db,course_id,user,body)


@router.get('/courses/{course_id}/problems')
def problems(course_id:Id,user:User=Depends(current_user),db:Session=Depends(get_db),
             q:str=Query(default='',max_length=100),question_type:QuestionType|None=None,
             status:str|None=Query(default='ACTIVE',pattern='^(ACTIVE|ARCHIVED)$'),
             limit:int=Query(default=20,ge=1,le=100),offset:int=Query(default=0,ge=0)):
    return problem_service.list_problems(db,course_id,user,q,question_type,status,limit,offset)


@router.post('/courses/{course_id}/problems',status_code=201)
def create_problem(course_id:Id,body:ProblemCreate,user:User=Depends(current_user),db:Session=Depends(get_db)):
    with write_transaction(db):
        return problem_service.create_problem(db,course_id,user,body)


@router.get('/problems/{problem_id}')
def problem_detail(problem_id:Id,user:User=Depends(current_user),db:Session=Depends(get_db)):
    problem=problem_service.problem_context(db,problem_id,user)
    versions=list(db.scalars(select(ProblemVersion).where(ProblemVersion.problem_id==problem.id)
                             .order_by(ProblemVersion.version_no.desc())))
    return {'id':str(problem.id),'course_id':str(problem.course_id),'code':problem.code,
        'question_type':problem.question_type,'status':problem.status,
        'versions':[{'id':str(v.id),'version_no':v.version_no,'title':v.title,'status':v.status,
                     'updated_at':iso(v.updated_at),'frozen_at':iso(v.frozen_at)} for v in versions],
        'latest_version':problem_service.version_view(db,problem,versions[0]) if versions else None}


@router.get('/problem-versions/{version_id}')
def version_detail(version_id:Id,user:User=Depends(current_user),db:Session=Depends(get_db)):
    problem,version=problem_service.version_context(db,version_id,user)
    return problem_service.version_view(db,problem,version)


@router.put('/problem-versions/{version_id}')
def edit_version(version_id:Id,body:VersionUpdate,user:User=Depends(current_user),db:Session=Depends(get_db)):
    with write_transaction(db):
        return problem_service.update_version(db,version_id,user,body)


@router.post('/problems/{problem_id}/versions',status_code=201)
def fork_version(problem_id:Id,body:VersionFork,user:User=Depends(current_user),db:Session=Depends(get_db)):
    with write_transaction(db):
        return problem_service.fork_version(db,problem_id,user,body)


@router.post('/problem-versions/{version_id}/freeze')
def freeze_version(version_id:Id,body:VersionAction,user:User=Depends(current_user),db:Session=Depends(get_db)):
    with write_transaction(db):
        return problem_service.freeze_version(db,version_id,user,body)


@router.post('/problems/{problem_id}/archive')
def archive_problem(problem_id:Id,user:User=Depends(current_user),db:Session=Depends(get_db)):
    with write_transaction(db):
        problem=problem_service.problem_context(db,problem_id,user,lock=True)
        problem.status='ARCHIVED'
        db.flush()
        return {'id':str(problem.id),'status':problem.status}


@router.post('/problems/{problem_id}/restore')
def restore_problem(problem_id:Id,user:User=Depends(current_user),db:Session=Depends(get_db)):
    with write_transaction(db):
        problem=problem_service.problem_context(db,problem_id,user,lock=True)
        problem.status='ACTIVE'
        db.flush()
        return {'id':str(problem.id),'status':problem.status}


@router.get('/courses/{course_id}/students')
def students(course_id:Id,user:User=Depends(current_user),db:Session=Depends(get_db),
             q:str=Query(default='',max_length=100),class_id:int|None=Query(default=None,gt=0,le=9223372036854775807),
             limit:int=Query(default=20,ge=1,le=100),offset:int=Query(default=0,ge=0)):
    return student_service.list_students(db,course_id,user,q,class_id,limit,offset)


@router.get('/courses/{course_id}/classes')
def classes(course_id:Id,user:User=Depends(current_user),db:Session=Depends(get_db)):
    return student_service.list_classes(db,course_id,user)


@router.get('/courses/{course_id}/students/import/template')
def student_template(course_id:Id,user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_teacher(db,course_id,user.id)
    template='student_no,full_name,class_name,class_code\r\n001001,示例学生甲,示例一班,\r\n001002,示例学生乙,示例一班,\r\n'
    return Response(template.encode('utf-8-sig'),media_type='text/csv; charset=utf-8',
                    headers={'Content-Disposition':'attachment; filename="students-template.csv"'})


def read_csv_upload(file):
    raw=file.file.read(student_service.MAX_CSV_BYTES+1)
    if len(raw)>student_service.MAX_CSV_BYTES:
        raise AppError(422,'INVALID_CSV_SIZE','CSV 文件不能超过 2 MiB')
    return raw


@router.post('/courses/{course_id}/students/import/preview')
def preview_roster(course_id:Id,file:UploadFile=File(),user:User=Depends(current_user),db:Session=Depends(get_db)):
    # Permission precedes reading or interpreting the uploaded roster.
    require_teacher(db,course_id,user.id)
    return student_service.preview_import(db,course_id,user,read_csv_upload(file))


@router.post('/courses/{course_id}/students/import/confirm')
def confirm_roster(course_id:Id,file:UploadFile=File(),
                   expected_sha256:str=Form(pattern='^[a-f0-9]{64}$'),
                   preview_token:str=Form(min_length=1,max_length=2048),allow_updates:bool=Form(default=False),
                   user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_teacher(db,course_id,user.id)
    with write_transaction(db):
        result=student_service.confirm_import(db,course_id,user,read_csv_upload(file),
                                              expected_sha256,preview_token,allow_updates)
    # No names, student numbers, content or authentication credentials enter logs.
    logger.info('teacher_roster_import course=%s actor=%s rows=%s sha256=%s',
                course_id,user.id,result['rows'],result['content_sha256'])
    return result


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
