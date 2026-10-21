from sqlalchemy import select
from app.core.errors import AppError
from app.db.models import Course, CourseMember, AssignmentParticipant


def course_role(db, course_id: int, user_id: int) -> str:
    role=db.scalar(select(CourseMember.role).join(Course,CourseMember.course_id==Course.id).where(
        CourseMember.course_id==course_id, CourseMember.user_id==user_id,
        CourseMember.status=='ACTIVE', Course.status=='ACTIVE'))
    if role is None:
        raise AppError(404,'NOT_FOUND','资源不存在或不可访问')
    return role


def require_teacher(db, course_id: int, user_id: int):
    if course_role(db,course_id,user_id)!='TEACHER':
        raise AppError(403,'TEACHER_REQUIRED','此操作需要任课教师身份')


def participant(db, assignment_id: int, student_id: int, lock=False):
    statement=select(AssignmentParticipant).where(AssignmentParticipant.assignment_id==assignment_id,
                                                AssignmentParticipant.student_id==student_id)
    if lock:
        statement=statement.with_for_update()
    row=db.scalar(statement)
    if row is None:
        raise AppError(404,'NOT_FOUND','资源不存在或不可访问')
    return row
