from datetime import datetime, timedelta, timezone
import os
import secrets

from fastapi import APIRouter, Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core import limits, ratelimit
from app.core.config import Settings
from app.core.errors import AppError
from app.db.base import utcnow
from app.db.session import get_db
from app.db.models import User, AuthSession, RequestRateLimit
from app.common.security import hash_password, verify_password, token_hash

router = APIRouter(prefix='/api/v1/auth', tags=['账户'])
bearer = HTTPBearer(auto_error=False)
DUMMY_PASSWORD = hash_password(secrets.token_urlsafe(24))

IDLE_WINDOW = timedelta(hours=2)
ABSOLUTE_WINDOW = timedelta(hours=24)
PASSWORD_MIN_LENGTH = 8
PASSWORD_MAX_LENGTH = 128


class LoginInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    login_name: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=1024)


class ChangePasswordInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    current_password: str = Field(min_length=1, max_length=1024)
    new_password: str = Field(min_length=1, max_length=1024)


def user_view(user: User):
    return {'id': str(user.id), 'login_name': user.login_name, 'full_name': user.full_name,
            'must_change_password': bool(user.must_change_password)}


def client_ip(request: Request) -> str:
    """Only trust forwarding headers when the deployment declares a trusted proxy."""
    host = request.client.host if request.client else 'unknown'
    if os.getenv('TRUST_PROXY_HEADERS', '').strip().lower() in {'1', 'true', 'yes'}:
        forwarded = request.headers.get('x-forwarded-for', '').split(',')[0].strip()
        if forwarded:
            host = forwarded
    return host


def _utc(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _session_payload(session: AuthSession, user: User, now: datetime) -> dict:
    return {
        'user': user_view(user),
        'must_change_password': bool(user.must_change_password),
        'server_time': _utc(now),
        'expires_at': _utc(session.expires_at),
        'absolute_expires_at': _utc(session.absolute_expires_at),
    }


def _login_payload(session: AuthSession, user: User, token: str, now: datetime) -> dict:
    payload = _session_payload(session, user, now)
    expires_in = max(0, int((session.expires_at - now).total_seconds()))
    return {'access_token': token, 'token_type': 'bearer', 'expires_in': expires_in, **payload}


def _new_token() -> str:
    return secrets.token_urlsafe(32)


def _session_row(session: AuthSession, now: datetime) -> bool:
    expires = session.expires_at
    absolute = session.absolute_expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if absolute.tzinfo is None:
        absolute = absolute.replace(tzinfo=timezone.utc)
    return expires > now and absolute > now


def resolve_session(request: Request, credentials: HTTPAuthorizationCredentials | None,
                    db: Session) -> tuple[User, AuthSession]:
    if credentials is None or len(credentials.credentials) > 200:
        raise AppError(401, 'AUTH_REQUIRED', '请先登录')
    digest = token_hash(credentials.credentials, Settings.load().secret)
    row = db.execute(select(User, AuthSession).join(AuthSession, AuthSession.user_id == User.id).where(
        AuthSession.token_hash == digest)).first()
    now = utcnow()
    if row is None or row[0].status != 'ACTIVE' or not _session_row(row[1], now):
        raise AppError(401, 'AUTH_EXPIRED', '登录已失效，请重新登录')
    request.state.auth_session_id = row[1].id
    request.state.auth_session = row[1]
    return row[0], row[1]


def authenticated_user(request: Request, credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
                       db: Session = Depends(get_db)) -> User:
    """Identity dependency that still allows the forced password change screens."""
    user, _ = resolve_session(request, credentials, db)
    return user


def current_user(request: Request, credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
                 db: Session = Depends(get_db)) -> User:
    """Business dependency: first-login password change must be completed."""
    user, _ = resolve_session(request, credentials, db)
    if user.must_change_password:
        raise AppError(403, 'PASSWORD_CHANGE_REQUIRED', '首次登录需要先修改密码')
    return user


def _enforce_login_limits(db: Session, request: Request, name: str) -> str:
    ip = client_ip(request)
    account_limit = limits.login_account_per_minute()
    ip_limit = limits.login_ip_per_minute()
    ratelimit.enforce(db, 'login_account', ratelimit.subject_key(f'{name}|{ip}'), account_limit, 60,
                      message='登录尝试过于频繁，请稍后再试')
    ratelimit.enforce(db, 'login_ip', ratelimit.subject_key(ip), ip_limit, 60,
                      message='来源请求过于频繁，请稍后再试')
    failure_key = ratelimit.subject_key(f'{name}|{ip}')
    failures, retry_after_at = ratelimit.peek(db, 'login_failure', failure_key,
                                              limits.login_failure_window_seconds())
    if failures >= limits.login_failure_limit():
        db.commit()
        retry_after = max(1, int((retry_after_at - utcnow()).total_seconds()))
        raise AppError(429, 'LOGIN_COOLDOWN', '登录失败次数过多，请稍后再试',
                       {'retry_after_at': retry_after_at.isoformat()},
                       headers={'Retry-After': str(retry_after)})
    return failure_key


def issue_initial_password(db: Session, user_id: int, expected_updated_at: datetime,
                           *, activate: bool) -> tuple[User, str]:
    """Shared account mutation. Caller authorizes the target and owns the transaction.

    The same fresh user-row lock as login/change-password serializes all credential
    writes. Secrets are returned once to the authorized caller, never persisted.
    """
    user = db.scalar(select(User).where(User.id == user_id).with_for_update()
                     .execution_options(populate_existing=True))
    if user is None:
        raise AppError(404, 'NOT_FOUND', '学生不存在或不可访问')
    if user.updated_at != expected_updated_at:
        raise AppError(409, 'ACCOUNT_CONFLICT', '账号已发生变化，请刷新名单后重试')
    if user.status != ('PENDING' if activate else 'ACTIVE'):
        raise AppError(409, 'ACCOUNT_STATE_CONFLICT', '仅待开通账号可开通，仅启用账号可重置密码')
    password = secrets.token_urlsafe(18)
    user.password_hash = hash_password(password)
    user.must_change_password = True
    user.password_updated_at = utcnow()
    user.updated_at = utcnow()
    user.status = 'ACTIVE'
    db.execute(delete(AuthSession).where(AuthSession.user_id == user.id))
    db.flush()
    return user, password


@router.post('/login')
def login(body: LoginInput, request: Request, db: Session = Depends(get_db)):
    name = body.login_name.strip().casefold()
    failure_key = _enforce_login_limits(db, request, name)
    db.commit()
    # Serialize password verification with password changes and resets on the same user row.
    # populate_existing forces a fresh read instead of reusing an ORM identity-map value.
    user = db.scalar(select(User).where(User.login_name == name).with_for_update()
                     .execution_options(populate_existing=True))
    valid = verify_password(body.password, user.password_hash if user else DUMMY_PASSWORD)
    if not valid or user is None or user.status != 'ACTIVE':
        ratelimit.hit(db, 'login_failure', failure_key, limits.login_failure_limit(),
                      limits.login_failure_window_seconds())
        db.commit()
        raise AppError(401, 'INVALID_CREDENTIALS', '账号或密码不正确，或账号不可用')
    db.execute(delete(AuthSession).where(AuthSession.user_id == user.id, AuthSession.expires_at <= utcnow()))
    db.execute(delete(RequestRateLimit).where(RequestRateLimit.bucket == 'login_failure',
                                              RequestRateLimit.subject_hash == failure_key))
    now = utcnow()
    token = _new_token()
    session = AuthSession(user_id=user.id, token_hash=token_hash(token, Settings.load().secret),
                          expires_at=now + IDLE_WINDOW, last_active_at=now,
                          absolute_expires_at=now + ABSOLUTE_WINDOW)
    db.add(session)
    db.flush()
    payload = _login_payload(session, user, token, now)
    db.commit()
    return payload


@router.get('/session')
def session_view(request: Request, user: User = Depends(authenticated_user)):
    return _session_payload(request.state.auth_session, user, utcnow())


@router.post('/renew')
def renew(request: Request, user: User = Depends(authenticated_user), db: Session = Depends(get_db)):
    now = utcnow()
    session = db.scalar(select(AuthSession).where(AuthSession.id == request.state.auth_session_id)
                        .with_for_update())
    if session is None or not _session_row(session, now):
        raise AppError(401, 'AUTH_EXPIRED', '登录已失效，请重新登录')
    session.last_active_at = now
    session.expires_at = min(now + IDLE_WINDOW, session.absolute_expires_at)
    db.commit()
    return {'server_time': _utc(now), 'expires_at': _utc(session.expires_at),
            'absolute_expires_at': _utc(session.absolute_expires_at),
            'must_change_password': bool(user.must_change_password)}


@router.post('/change-password')
def change_password(body: ChangePasswordInput, request: Request, user: User = Depends(authenticated_user),
                    db: Session = Depends(get_db)):
    if body.new_password == body.current_password:
        raise AppError(422, 'PASSWORD_UNCHANGED', '新密码不能与当前密码相同')
    if not PASSWORD_MIN_LENGTH <= len(body.new_password) <= PASSWORD_MAX_LENGTH:
        raise AppError(422, 'PASSWORD_POLICY', f'密码长度需为 {PASSWORD_MIN_LENGTH}～{PASSWORD_MAX_LENGTH} 个字符')
    locked = db.scalar(select(User).where(User.id == user.id).with_for_update()
                       .execution_options(populate_existing=True))
    if locked is None or not verify_password(body.current_password, locked.password_hash):
        # The session may belong to an account whose password was just reset by a teacher.
        raise AppError(401, 'INVALID_CREDENTIALS', '当前密码不正确')
    now = utcnow()
    current = db.get(AuthSession, request.state.auth_session_id)
    absolute = current.absolute_expires_at if current is not None else now + ABSOLUTE_WINDOW
    locked.password_hash = hash_password(body.new_password)
    locked.must_change_password = False
    locked.password_updated_at = now
    db.execute(delete(AuthSession).where(AuthSession.user_id == locked.id))
    db.flush()
    token = _new_token()
    session = AuthSession(user_id=locked.id, token_hash=token_hash(token, Settings.load().secret),
                          expires_at=min(now + IDLE_WINDOW, absolute), last_active_at=now,
                          absolute_expires_at=absolute)
    db.add(session)
    db.flush()
    payload = _login_payload(session, locked, token, now)
    db.commit()
    return payload


@router.post('/logout')
def logout(request: Request, user: User = Depends(authenticated_user), db: Session = Depends(get_db)):
    row = db.get(AuthSession, request.state.auth_session_id)
    if row is not None:
        db.delete(row)
        db.commit()
    return {'status': 'logged_out'}
