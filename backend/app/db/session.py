from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from starlette.requests import Request

from app.core.config import Settings


def make_engine():
    return create_engine(Settings.load().url(), pool_pre_ping=True, pool_recycle=1800, isolation_level='READ COMMITTED',
                         hide_parameters=True, connect_args={'connect_timeout': 5})


def get_db(request: Request):
    if request.app.state.engine is None:
        request.app.state.engine = make_engine()
    with sessionmaker(bind=request.app.state.engine, expire_on_commit=False)() as session:
        try:
            yield session
        except Exception:
            session.rollback()
            raise
