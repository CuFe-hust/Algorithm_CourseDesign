from datetime import datetime
from sqlalchemy import ForeignKey, String, UniqueConstraint, CheckConstraint
from sqlalchemy.dialects.mysql import BIGINT, DATETIME
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base, Mutable


class User(Mutable, Base):
    __tablename__ = 'users'
    login_name: Mapped[str] = mapped_column(String(64), unique=True)
    student_no: Mapped[str | None] = mapped_column(String(32), unique=True)
    full_name: Mapped[str] = mapped_column(String(100))
    password_hash: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(16), default='PENDING')
    __table_args__ = (CheckConstraint("status IN ('PENDING','ACTIVE','DISABLED')", name='ck_user_status'),)


class Class(Mutable, Base):
    __tablename__ = 'classes'
    class_code: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(16), default='ACTIVE')


class StudentProfile(Mutable, Base):
    __tablename__ = 'student_profiles'
    user_id: Mapped[int] = mapped_column(BIGINT(unsigned=True), ForeignKey('users.id'), unique=True)
    class_id: Mapped[int] = mapped_column(BIGINT(unsigned=True), ForeignKey('classes.id'), index=True)


class Course(Mutable, Base):
    __tablename__ = 'courses'
    code: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    term: Mapped[str] = mapped_column(String(32))
    created_by: Mapped[int] = mapped_column(BIGINT(unsigned=True), ForeignKey('users.id'))
    status: Mapped[str] = mapped_column(String(16), default='ACTIVE')


class CourseMember(Mutable, Base):
    __tablename__ = 'course_members'
    course_id: Mapped[int] = mapped_column(BIGINT(unsigned=True), ForeignKey('courses.id'))
    user_id: Mapped[int] = mapped_column(BIGINT(unsigned=True), ForeignKey('users.id'), index=True)
    role: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), default='ACTIVE')
    __table_args__ = (UniqueConstraint('course_id', 'user_id'),
                     CheckConstraint("role IN ('TEACHER','STUDENT')", name='ck_member_role'))


class AuthSession(Base):
    __tablename__ = 'auth_sessions'
    user_id: Mapped[int] = mapped_column(BIGINT(unsigned=True), ForeignKey('users.id'), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6), index=True)
