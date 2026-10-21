from datetime import timedelta
import secrets
from fastapi import APIRouter, Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.config import Settings
from app.core.errors import AppError
from app.db.base import utcnow
from app.db.session import get_db
from app.db.models import User, AuthSession
from app.common.security import hash_password, verify_password, token_hash

router = APIRouter(prefix='/api/v1/auth', tags=['账户'])
bearer = HTTPBearer(auto_error=False)
DUMMY_PASSWORD = hash_password(secrets.token_urlsafe(24))


class LoginInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    login_name: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=1024)


def user_view(user: User):
    return {'id':str(user.id), 'login_name':user.login_name, 'full_name':user.full_name}


def current_user(request: Request, credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
                 db: Session = Depends(get_db)) -> User:
    if credentials is None or len(credentials.credentials) > 200:
        raise AppError(401,'AUTH_REQUIRED','请先登录')
    digest = token_hash(credentials.credentials, Settings.load().secret)
    row = db.execute(select(User, AuthSession).join(AuthSession, AuthSession.user_id==User.id).where(
        AuthSession.token_hash==digest, AuthSession.expires_at>utcnow(), User.status=='ACTIVE')).first()
    if row is None:
        raise AppError(401,'AUTH_EXPIRED','登录已失效，请重新登录')
    request.state.auth_session_id = row[1].id
    return row[0]


@router.post('/login')
def login(body: LoginInput, db: Session = Depends(get_db)):
    name=body.login_name.strip().casefold()
    user=db.scalar(select(User).where(User.login_name==name))
    valid=verify_password(body.password, user.password_hash if user else DUMMY_PASSWORD)
    if not valid or user is None or user.status!='ACTIVE':
        raise AppError(401,'INVALID_CREDENTIALS','账号或密码不正确，或账号不可用')
    token=secrets.token_urlsafe(32)
    db.add(AuthSession(user_id=user.id, token_hash=token_hash(token,Settings.load().secret), expires_at=utcnow()+timedelta(hours=2)))
    db.commit()
    return {'access_token':token,'token_type':'bearer','expires_in':7200,'user':user_view(user)}


@router.post('/logout')
def logout(request: Request, user: User=Depends(current_user), db: Session=Depends(get_db)):
    row=db.get(AuthSession,request.state.auth_session_id)
    db.delete(row);db.commit()
    return {'status':'logged_out'}
