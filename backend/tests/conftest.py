import secrets
import pytest
from sqlalchemy import delete
from sqlalchemy.orm import Session
from fastapi.testclient import TestClient
from app.db.base import Base
from app.db import models
from app.db.session import make_engine, get_db


@pytest.fixture
def db(monkeypatch):
    monkeypatch.setenv('DB_NAME', 'algorithm_review_test')
    engine = make_engine()
    assert engine.url.database == 'algorithm_review_test'
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
def auth(client, demo):
    summary, password = demo
    def login(name='demo.student01'):
        response = client.post('/api/v1/auth/login', json={'login_name':name, 'password':password})
        assert response.status_code == 200, response.text
        return {'Authorization':'Bearer '+response.json()['access_token']}
    return login
