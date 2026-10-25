"""Authorized, one-time delivery of initial student credentials."""
from sqlalchemy import select

from app.common.auth import issue_initial_password
from app.common.permissions import require_teacher
from app.core.errors import AppError
from app.db.models import CourseMember, StudentProfile, User
from app.student.service import iso


def issue_accounts(db, course_id, actor, body):
    require_teacher(db, course_id, actor.id)
    credentials = []
    # Stable lock order also supports two teachers issuing overlapping batches.
    for target in sorted(body.students, key=lambda row: row.student_id):
        member = db.scalar(select(CourseMember).where(CourseMember.course_id == course_id,
            CourseMember.user_id == target.student_id, CourseMember.role == 'STUDENT',
            CourseMember.status == 'ACTIVE'))
        if member is None or db.scalar(select(StudentProfile.id).where(
                StudentProfile.user_id == target.student_id)) is None:
            raise AppError(404, 'NOT_FOUND', '学生不存在或不属于当前课程')
        if db.scalar(select(CourseMember.id).where(CourseMember.user_id == target.student_id,
                CourseMember.role == 'TEACHER', CourseMember.status == 'ACTIVE').limit(1)):
            raise AppError(403, 'STUDENT_ACCOUNT_REQUIRED', '不能通过学生管理修改教师账号')
        user, password = issue_initial_password(db, target.student_id, target.expected_updated_at,
                                                 activate=body.action == 'ACTIVATE')
        credentials.append({'student_id': str(user.id), 'student_no': user.student_no,
            'full_name': user.full_name, 'login_name': user.login_name,
            'initial_password': password, 'updated_at': iso(user.updated_at)})
    return {'credentials': credentials, 'must_change_password': True, 'issued_at': iso(user.password_updated_at)}
