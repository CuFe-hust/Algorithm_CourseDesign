from datetime import datetime
from sqlalchemy import ForeignKey, String, UniqueConstraint, CheckConstraint
from sqlalchemy import BigInteger, Boolean, DateTime, Integer
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base, Mutable, utcnow


class User(Mutable, Base):
    __tablename__ = 'users'
    login_name: Mapped[str] = mapped_column(String(64), unique=True)
    student_no: Mapped[str | None] = mapped_column(String(32), unique=True)
    full_name: Mapped[str] = mapped_column(String(100))
    password_hash: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(16), default='PENDING')
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False)
    password_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (CheckConstraint("status IN ('PENDING','ACTIVE','DISABLED')", name='ck_user_status'),)


class Class(Mutable, Base):
    __tablename__ = 'classes'
    class_code: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(16), default='ACTIVE')


class StudentProfile(Mutable, Base):
    __tablename__ = 'student_profiles'
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('users.id'), unique=True)
    class_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('classes.id'), index=True)


class Course(Mutable, Base):
    __tablename__ = 'courses'
    code: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    term: Mapped[str] = mapped_column(String(32))
    created_by: Mapped[int] = mapped_column(BigInteger, ForeignKey('users.id'))
    status: Mapped[str] = mapped_column(String(16), default='ACTIVE')


class CourseMember(Mutable, Base):
    __tablename__ = 'course_members'
    course_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('courses.id'))
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('users.id'), index=True)
    role: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), default='ACTIVE')
    __table_args__ = (UniqueConstraint('course_id', 'user_id'),
                     CheckConstraint("role IN ('TEACHER','STUDENT')", name='ck_member_role'))


class AuthSession(Base):
    __tablename__ = 'auth_sessions'
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('users.id'), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    last_active_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    absolute_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class RequestRateLimit(Base):
    """Shared, bounded counter used by every API process for coarse throttling.

    A row is one (bucket, subject, fixed window) tuple. Counting uses a single
    upsert statement so concurrent workers cannot overshoot the quota, and rows
    expire independently from business idempotency records.
    """
    __tablename__ = 'request_rate_limits'
    bucket: Mapped[str] = mapped_column(String(32))
    subject_hash: Mapped[str] = mapped_column(String(64))
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    window_seconds: Mapped[int] = mapped_column(Integer)
    counter: Mapped[int] = mapped_column(Integer, default=0)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    __table_args__ = (UniqueConstraint('bucket', 'subject_hash', 'window_start', 'window_seconds'),
                      CheckConstraint('counter >= 0', name='ck_rate_limit_counter'),
                      CheckConstraint('window_seconds > 0', name='ck_rate_limit_window'))
