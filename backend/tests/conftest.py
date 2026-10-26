import os
import secrets
import tempfile

import pytest

# The managed sandbox denies directory creation under the default per-user temp
# root, so keep pytest's temporary directories inside /tmp.
if os.name != 'nt':
    os.environ['TMPDIR'] = '/tmp'
    tempfile.tempdir = '/tmp'

from sqlalchemy import delete
from sqlalchemy.orm import Session
from fastapi.testclient import TestClient
from app.db.base import Base
from app.db import models
from app.db.session import make_engine, get_db


def pytest_configure(config):
    """Use a fresh per-run base temp directory.

    The managed sandbox rejects ``mkdir`` on a directory that already exists, so
    pytest must not reuse a previous run's ``pytest-of-*`` folder.
    """
    if not config.option.basetemp:
        config.option.basetemp = os.path.join(tempfile.gettempdir(), f'algoclass-pytest-{os.getpid()}')


@pytest.fixture
def db(monkeypatch):
    monkeypatch.setenv('DB_NAME', 'algorithm_review_test')
    engine = make_engine()
    assert engine.url.database == 'algorithm_review_test'
    assert engine.dialect.name == 'postgresql'
    with engine.begin() as connection:
        for table in reversed(Base.metadata.sorted_tables):
            connection.execute(delete(table))
    with Session(engine, expire_on_commit=False) as session:
        yield session
        session.rollback()
    engine.dispose()


@pytest.fixture
def demo(db):
    from app.demo import seed_demo
    password = secrets.token_urlsafe(24)
    return seed_demo(db, password), password


@pytest.fixture
def client(db):
    from app.main import create_app
    application = create_app()
    application.state.engine = db.bind
    def override():
        try:
            yield db
        except Exception:
            db.rollback()
            raise
    application.dependency_overrides[get_db] = override
    with TestClient(application, raise_server_exceptions=False) as result:
        yield result


@pytest.fixture
def live_client(db):
    """A client without a shared session override: every request opens its own transaction.

    Required for tests that verify row-lock protocols, because a single shared
    session cannot represent two concurrent connections.
    """
    from app.main import create_app
    application = create_app()
    application.state.engine = db.bind
    with TestClient(application, raise_server_exceptions=False) as result:
        db.expire_all()
        yield result


@pytest.fixture
def auth(client, demo):
    summary, password = demo
    def login(name='demo.student01'):
        response = client.post('/api/v1/auth/login', json={'login_name':name, 'password':password})
        assert response.status_code == 200, response.text
        return {'Authorization':'Bearer '+response.json()['access_token']}
    return login


@pytest.fixture
def judge_work_root(tmp_path, monkeypatch):
    root = tmp_path / 'judge-work'
    root.mkdir()
    monkeypatch.setenv('JUDGE_WORK_ROOT', str(root))
    monkeypatch.setenv('JUDGE_LOCK_ROOT', str(root / 'locks'))
    return root
