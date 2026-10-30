from contextlib import asynccontextmanager
import logging
import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException
from sqlalchemy import text
from alembic.config import Config
from alembic.script import ScriptDirectory
from app.core.config import ROOT

from app.core.errors import AppError, error_response
from app.core.bodylimit import BodyLimitMiddleware
from app.db.session import make_engine
from app.common.auth import router as auth_router
from app.student.router import router as student_router
from app.teacher.router import router as teacher_router
from app.analysis.router import router as analysis_router
from app.peer_review.router import router as peer_review_router


def create_app() -> FastAPI:
    @asynccontextmanager
    async def lifespan(application):
        yield
        if application.state.engine is not None:
            application.state.engine.dispose()

    application = FastAPI(title='算法课程评审平台 · 公共底座', version='0.1.0', lifespan=lifespan)
    application.state.engine = None
    application.include_router(auth_router)
    application.include_router(student_router)
    application.include_router(teacher_router)
    application.include_router(analysis_router)
    application.include_router(peer_review_router)

    @application.middleware('http')
    async def identify(request, call_next):
        request.state.request_id = uuid.uuid4().hex
        try:
            response = await call_next(request)
        except Exception:
            response = error_response(request, 500, 'INTERNAL_ERROR', '服务暂时不可用，请保留请求编号')
        response.headers['X-Request-ID'] = request.state.request_id
        return response

    @application.exception_handler(AppError)
    async def application_error(request: Request, exc: AppError):
        return error_response(request, exc.status, exc.code, exc.message, exc.details, exc.headers)

    @application.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        details = [{'field': '.'.join(map(str, e['loc'])), 'type': e['type']} for e in exc.errors()]
        return error_response(request, 422, 'VALIDATION_ERROR', '请求字段无效', details)

    @application.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        return error_response(request, exc.status_code, 'HTTP_ERROR', str(exc.detail))

    @application.exception_handler(Exception)
    async def internal_error(request: Request, exc: Exception):
        # Log the failure with the request id, but never leak internals to the client.
        logging.getLogger('app').exception('unhandled error request_id=%s', getattr(request.state, 'request_id', ''))
        return error_response(request, 500, 'INTERNAL_ERROR', '服务暂时不可用，请保留请求编号')

    @application.get('/api/v1/health')
    def health():
        return {'status': 'ok'}

    @application.get('/api/v1/ready')
    def ready():
        try:
            if application.state.engine is None:
                application.state.engine = make_engine()
            with application.state.engine.connect() as connection:
                versions = set(connection.scalars(text('SELECT version_num FROM alembic_version')))
            expected = set(ScriptDirectory.from_config(Config(str(ROOT / 'backend/alembic.ini'))).get_heads())
            if not expected or versions != expected:
                raise ValueError('Migration mismatch')
            return {'status': 'ready', 'migration': sorted(versions)[0]}
        except Exception:
            raise AppError(503, 'DATABASE_NOT_READY', '数据库或迁移尚未就绪')

    # Outermost user middleware: also decorate failures caught by identify.
    application.add_middleware(BodyLimitMiddleware)
    application.add_middleware(CORSMiddleware,
        allow_origins=['http://localhost:5173', 'http://127.0.0.1:5173'],
        allow_methods=['GET', 'POST', 'PUT'], allow_headers=['Authorization', 'Content-Type'],
        expose_headers=['X-Request-ID', 'Retry-After'])
    return application


app = create_app()
