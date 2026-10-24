"""AC03–AC07, AC27, AC31 and RV02: session lifecycle, forced password change and auth races."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.db.base import utcnow
from app.db.models import AuthSession, User


def _user(db, name='demo.student01'):
    return db.scalar(select(User).where(User.login_name == name))


def _login(client, password, name='demo.student01'):
    return client.post('/api/v1/auth/login', json={'login_name': name, 'password': password})


def test_first_login_requires_password_change_and_revokes_old_token(client, demo, db):
    user = _user(db)
    user.must_change_password = True
    db.commit()
    password = demo[1]
    response = _login(client, password)
    assert response.status_code == 200
    body = response.json()
    assert body['must_change_password'] is True
    assert body['expires_in'] > 7000
    absolute = body['absolute_expires_at']
    old = {'Authorization': 'Bearer ' + body['access_token']}

    assert client.get('/api/v1/courses', headers=old).status_code == 403
    assert client.get('/api/v1/courses', headers=old).json()['code'] == 'PASSWORD_CHANGE_REQUIRED'
    session = client.get('/api/v1/auth/session', headers=old)
    assert session.status_code == 200 and session.json()['must_change_password'] is True
    assert session.json()['absolute_expires_at'] == absolute

    assert client.post('/api/v1/auth/change-password', headers=old,
                       json={'current_password': 'wrong', 'new_password': 'brand-new-secret'}).status_code == 401
    assert client.post('/api/v1/auth/change-password', headers=old,
                       json={'current_password': password, 'new_password': password}).json()['code'] == 'PASSWORD_UNCHANGED'
    assert client.post('/api/v1/auth/change-password', headers=old,
                       json={'current_password': password, 'new_password': 'short'}).json()['code'] == 'PASSWORD_POLICY'

    changed = client.post('/api/v1/auth/change-password', headers=old,
                          json={'current_password': password, 'new_password': 'brand-new-secret'})
    assert changed.status_code == 200, changed.text
    payload = changed.json()
    assert payload['must_change_password'] is False
    assert payload['absolute_expires_at'] == absolute  # the 24h ceiling is inherited, not restarted
    fresh = {'Authorization': 'Bearer ' + payload['access_token']}
    assert client.get('/api/v1/courses', headers=fresh).status_code == 200
    assert client.get('/api/v1/courses', headers=old).status_code == 401
    db.expire_all()
    assert _user(db).must_change_password is False
    assert _user(db).password_updated_at is not None


def test_renew_extends_idle_window_only_and_never_revives_a_session(client, demo, db):
    password = demo[1]
    token = _login(client, password).json()['access_token']
    headers = {'Authorization': 'Bearer ' + token}
    user = _user(db)
    session = db.scalar(select(AuthSession).where(AuthSession.user_id == user.id))
    now = utcnow()
    session.expires_at = now + timedelta(seconds=30)
    session.absolute_expires_at = now + timedelta(seconds=90)
    db.commit()
    renewed = client.post('/api/v1/auth/renew', headers=headers)
    assert renewed.status_code == 200
    body = renewed.json()
    assert body['expires_at'] == body['absolute_expires_at']  # capped by the absolute deadline
    assert body['absolute_expires_at'] == session.absolute_expires_at.isoformat()

    session = db.get(AuthSession, session.id)
    session.absolute_expires_at = utcnow() - timedelta(seconds=1)
    db.commit()
    assert client.post('/api/v1/auth/renew', headers=headers).status_code == 401
    assert client.get('/api/v1/auth/session', headers=headers).status_code == 401

    db.expire_all()
    token = _login(client, password).json()['access_token']
    headers = {'Authorization': 'Bearer ' + token}
    assert client.post('/api/v1/auth/logout', headers=headers).status_code == 200
    assert client.post('/api/v1/auth/renew', headers=headers).status_code == 401


def test_renew_does_not_resurrect_expired_session_row(client, demo, db):
    password = demo[1]
    token = _login(client, password).json()['access_token']
    headers = {'Authorization': 'Bearer ' + token}
    user = _user(db)
    session = db.scalar(select(AuthSession).where(AuthSession.user_id == user.id))
    session.expires_at = utcnow() - timedelta(seconds=1)
    db.commit()
    assert client.post('/api/v1/auth/renew', headers=headers).status_code == 401
    db.expire_all()
    assert db.scalar(select(func.count()).select_from(AuthSession).where(AuthSession.user_id == user.id)) == 1


def test_login_and_change_password_are_serialized_on_the_user_row(demo, db, monkeypatch):
    """RV02: an old-password login may not slip in a session after the change commits."""
    from app.main import create_app
    monkeypatch.setenv('LIMIT_LOGIN_ACCOUNT_PER_MINUTE', '50')
    monkeypatch.setenv('LIMIT_LOGIN_FAILURES', '50')
    application = create_app()
    application.state.engine = db.bind
    password = demo[1]
    new_password = 'serialized-secret-1'
    with TestClient(application, raise_server_exceptions=False) as client:
        token = _login(client, password).json()['access_token']
    user = _user(db)
    headers = {'Authorization': 'Bearer ' + token}

    def attempt(kind: str):
        with TestClient(application, raise_server_exceptions=False) as local:
            if kind == 'login':
                return kind, local.post('/api/v1/auth/login',
                                        json={'login_name': 'demo.student01', 'password': password}).status_code
            return kind, local.post('/api/v1/auth/change-password', headers=headers,
                                    json={'current_password': password, 'new_password': new_password}).status_code

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(attempt, ['login', 'change'] * 4))

    changes = [code for kind, code in results if kind == 'change']
    assert changes.count(200) == 1, changes
    db.expire_all()
    sessions = db.scalar(select(func.count()).select_from(AuthSession).where(AuthSession.user_id == user.id))
    assert sessions == 1  # only the session issued by the successful password change survives
    with TestClient(application, raise_server_exceptions=False) as client:
        assert _login(client, password).status_code == 401
        assert _login(client, new_password).status_code == 200


def test_login_rate_limit_and_failure_cooldown(client, db, demo, monkeypatch):
    monkeypatch.setenv('LIMIT_LOGIN_ACCOUNT_PER_MINUTE', '2')
    monkeypatch.setenv('LIMIT_LOGIN_FAILURES', '3')
    monkeypatch.setenv('LIMIT_LOGIN_FAILURE_WINDOW_SECONDS', '600')
    statuses = [_login(client, 'definitely-wrong').status_code for _ in range(3)]
    assert statuses[:2] == [401, 401]
    assert statuses[2] == 429
    limited = _login(client, 'definitely-wrong')
    assert limited.status_code == 429
    assert 'Retry-After' in limited.headers
    assert limited.json()['code'] in {'RATE_LIMITED', 'LOGIN_COOLDOWN'}


def test_request_body_ceiling_rejects_declared_and_streamed_oversized_bodies(client, demo):
    oversized = client.post('/api/v1/auth/login',
                            json={'login_name': 'demo.student01', 'password': 'x' * 9000})
    assert oversized.status_code == 413
    assert oversized.json()['code'] == 'REQUEST_TOO_LARGE'

    streamed = client.post('/api/v1/auth/login',
                           content=iter([b'{"login_name":"a","password":"' + b'x' * 5000,
                                        b'y' * 5000 + b'"}']),
                           headers={'Content-Type': 'application/json'})
    assert streamed.status_code == 413

    submission = client.post(f"/api/v1/assignment-items/{demo[0]['items'][0]['id']}/submissions",
                             headers={'Authorization': 'Bearer fake', 'Content-Type': 'application/json'},
                             content=b'{"content":"' + b'x' * (3 * 1024 * 1024) + b'"}')
    assert submission.status_code == 413


def test_session_endpoint_reports_deadline_without_extending(client, demo, db):
    password = demo[1]
    token = _login(client, password).json()['access_token']
    headers = {'Authorization': 'Bearer ' + token}
    user = _user(db)
    session = db.scalar(select(AuthSession).where(AuthSession.user_id == user.id))
    original = (session.expires_at, session.absolute_expires_at)
    for _ in range(3):
        body = client.get('/api/v1/auth/session', headers=headers).json()
        assert body['user']['login_name'] == 'demo.student01'
        assert datetime.fromisoformat(body['expires_at']) == original[0]
    db.expire_all()
    session = db.get(AuthSession, session.id)
    assert (session.expires_at, session.absolute_expires_at) == original
