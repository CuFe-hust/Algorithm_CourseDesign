"""Teacher/student integration: account delivery, immutable publication and schedules."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import timedelta
import threading
import uuid

import pytest
from sqlalchemy import func, select

from app.db.base import utcnow
from app.db.models import (Assignment, AssignmentItem, AssignmentParticipant, AuthSession, Class,
    Course, CourseMember, ProblemVersion, StudentProfile, TestSuite as Suite, User)


@pytest.fixture
def setup(client, demo, auth):
    return auth('demo.teacher'), demo[0]['course_id'], auth(), demo[0]


def students(client, setup):
    teacher, course, _, _ = setup
    response = client.get(f'/api/v1/teacher/courses/{course}/students', headers=teacher)
    assert response.status_code == 200
    return response.json()['items']


def issue(client, setup, target, action='RESET'):
    return client.post(f'/api/v1/teacher/courses/{setup[1]}/students/credentials', headers=setup[0],
        json={'action': action, 'students': [{'student_id': target['id'], 'expected_updated_at': target['updated_at']}]})


def assignment_body(client, setup, mixed=False):
    choices = client.get(f'/api/v1/teacher/courses/{setup[1]}/assignment-choices?limit=100', headers=setup[0]).json()['items']
    chosen = choices if mixed else [next(c for c in choices if c['question_type'] == 'PROGRAMMING')]
    return {'title': '教师学生联调作业', 'description_md': '固定版本的合成作业',
        'submission_deadline': (utcnow()+timedelta(days=2)).isoformat(), 'review_deadline': None,
        'items': [{'problem_version_id': c['problem_version_id'], 'test_suite_id': c['test_suite_id'],
            'rubric_id': c['rubric_id'], 'max_score': '100.00',
            'required_reviewers': 0 if c['test_suite_id'] else 3} for c in chosen],
        'student_ids': [students(client, setup)[0]['id']]}


def create(client, setup, body):
    result = client.post(f'/api/v1/teacher/courses/{setup[1]}/assignments', headers=setup[0], json=body)
    assert result.status_code == 201, result.text
    return result.json()


def publish(client, setup, a, state='OPEN'):
    return client.post(f"/api/v1/teacher/assignments/{a['id']}/publish", headers=setup[0],
        json={'expected_updated_at': a['updated_at'], 'submission_status': state})


def test_import_activate_once_force_change_and_repeat_import_preserves_password(client, setup, db):
    teacher, course, _, _ = setup
    raw = 'student_no,full_name,class_name\n0019988,合成开通学生,合成开通班\n'.encode()
    path = f'/api/v1/teacher/courses/{course}/students/import'
    preview = client.post(path+'/preview', headers=teacher, files={'file': ('synthetic.csv', raw)}).json()
    params = {'expected_sha256': preview['content_sha256'], 'preview_token': preview['preview_token']}
    assert client.post(path+'/confirm', headers=teacher, files={'file': ('synthetic.csv', raw)}, data=params).status_code == 200
    target = next(s for s in students(client, setup) if s['student_no'] == '0019988')
    assert target['status'] == 'PENDING'
    response = issue(client, setup, target, 'ACTIVATE')
    assert response.status_code == 200 and response.headers['cache-control'] == 'no-store'
    credential = response.json()['credentials'][0]
    assert len(credential['initial_password']) >= 20
    assert issue(client, setup, target, 'ACTIVATE').status_code == 409
    user = db.get(User, int(target['id'])); original_hash = user.password_hash
    assert user.must_change_password and user.status == 'ACTIVE'
    assert credential['initial_password'] not in original_hash
    rows = students(client, setup)
    assert 'initial_password' not in str(rows) and 'password_hash' not in str(rows)
    preview = client.post(path+'/preview', headers=teacher, files={'file': ('synthetic.csv', raw)}).json()
    assert client.post(path+'/confirm', headers=teacher, files={'file': ('synthetic.csv', raw)},
        data={'expected_sha256': preview['content_sha256'], 'preview_token': preview['preview_token']}).status_code == 200
    db.expire_all(); assert db.get(User, user.id).password_hash == original_hash
    login = client.post('/api/v1/auth/login', json={'login_name': credential['login_name'], 'password': credential['initial_password']})
    assert login.status_code == 200 and login.json()['must_change_password']
    headers = {'Authorization': 'Bearer '+login.json()['access_token']}
    assert client.get('/api/v1/courses', headers=headers).status_code == 403
    changed = client.post('/api/v1/auth/change-password', headers=headers,
        json={'current_password': credential['initial_password'], 'new_password': 'synthetic-new-secret'})
    assert changed.status_code == 200 and not changed.json()['must_change_password']
    assert client.get('/api/v1/courses', headers=headers).status_code == 401


def test_reset_revokes_old_session_and_does_not_reenable_disabled_user(client, setup, demo, db):
    old_headers = setup[2]
    target = students(client, setup)[0]
    result = issue(client, setup, target)
    assert result.status_code == 200
    credential = result.json()['credentials'][0]
    assert client.get('/api/v1/auth/session', headers=old_headers).status_code == 401
    assert client.post('/api/v1/auth/renew', headers=old_headers).status_code == 401
    assert client.post('/api/v1/auth/login', json={'login_name': target['login_name'], 'password': demo[1]}).status_code == 401
    assert client.post('/api/v1/auth/login', json={'login_name': target['login_name'], 'password': credential['initial_password']}).json()['must_change_password']
    user = db.get(User, int(target['id'])); user.status = 'DISABLED'; db.commit()
    refreshed = next(s for s in students(client, setup) if s['id'] == target['id'])
    assert issue(client, setup, refreshed, 'ACTIVATE').status_code == 409
    assert issue(client, setup, refreshed).status_code == 409


def test_credential_batch_scope_rollback_and_unique_secrets(client, setup, db, auth):
    rows = students(client, setup); teacher, course, student, _ = setup
    before = db.get(User, int(rows[0]['id'])).password_hash
    params = {'action': 'RESET', 'students': [{'student_id': r['id'], 'expected_updated_at': r['updated_at']} for r in rows[:2]]}
    params['students'][1]['expected_updated_at'] = '2020-01-01T00:00:00Z'
    path = f'/api/v1/teacher/courses/{course}/students/credentials'
    assert client.post(path, headers=teacher, json=params).status_code == 409
    db.expire_all(); assert db.get(User, int(rows[0]['id'])).password_hash == before
    assert client.post(path, headers=student, json=params).status_code == 403
    other = Course(code='NO_ACCESS', name='其他课程', term='2026', created_by=db.scalar(select(User.id).where(User.login_name=='demo.teacher')))
    db.add(other); db.commit()
    assert client.post(f'/api/v1/teacher/courses/{other.id}/students/credentials', headers=teacher, json=params).status_code == 404
    params['students'][1]['expected_updated_at'] = rows[1]['updated_at']
    response = client.post(path, headers=teacher, json=params)
    assert response.status_code == 200
    assert len({c['initial_password'] for c in response.json()['credentials']}) == 2


def test_reset_and_old_password_login_share_one_row_lock(live_client, demo, db, monkeypatch):
    """Force the old login to hold the user lock, then reset and revoke its new session."""
    from app.common import auth as auth_service
    monkeypatch.setenv('LIMIT_LOGIN_ACCOUNT_PER_MINUTE', '50')
    password = demo[1]; course = demo[0]['course_id']
    teacher_token = live_client.post('/api/v1/auth/login', json={'login_name': 'demo.teacher', 'password': password}).json()['access_token']
    headers = {'Authorization': 'Bearer '+teacher_token}
    target = live_client.get(f'/api/v1/teacher/courses/{course}/students', headers=headers).json()['items'][0]
    acquired = threading.Event(); release = threading.Event(); original = auth_service.verify_password
    def delayed(value, hashed):
        if value == password:
            acquired.set(); assert release.wait(5)
        return original(value, hashed)
    monkeypatch.setattr(auth_service, 'verify_password', delayed)
    with ThreadPoolExecutor(max_workers=2) as pool:
        login = pool.submit(live_client.post, '/api/v1/auth/login', json={'login_name': target['login_name'], 'password': password})
        assert acquired.wait(5)
        reset = pool.submit(live_client.post, f'/api/v1/teacher/courses/{course}/students/credentials', headers=headers,
            json={'action':'RESET','students':[{'student_id':target['id'],'expected_updated_at':target['updated_at']}]})
        release.set()
        old = login.result(timeout=10); result = reset.result(timeout=10)
    assert old.status_code == 200 and result.status_code == 200
    assert live_client.get('/api/v1/auth/session', headers={'Authorization':'Bearer '+old.json()['access_token']}).status_code == 401
    db.expire_all(); assert db.scalar(select(func.count()).select_from(AuthSession).where(AuthSession.user_id==int(target['id']))) == 0
    assert live_client.post('/api/v1/auth/login', json={'login_name':target['login_name'],'password':password}).status_code == 401


def test_assignment_publish_visibility_pins_all_four_types_and_roster_snapshot(client, setup, auth, db):
    body = assignment_body(client, setup, mixed=True)
    a = create(client, setup, body)
    assert client.get(f"/api/v1/assignments/{a['id']}", headers=setup[2]).status_code == 404
    target = db.get(StudentProfile, db.scalar(select(StudentProfile.id).where(StudentProfile.user_id==int(body['student_ids'][0]))))
    other_class = db.scalar(select(Class).where(Class.id!=target.class_id)); target.class_id = other_class.id; db.commit()
    response = publish(client, setup, a)
    assert response.status_code == 200, response.text
    a = response.json(); assert a['participants'][0]['class_name_at_publish'] == other_class.name
    assert client.get(f"/api/v1/assignments/{a['id']}", headers=setup[2]).status_code == 200
    assert client.get(f"/api/v1/assignments/{a['id']}", headers=auth('demo.student02')).status_code == 404
    assert len(a['items']) == 4 and a['published_at'] and a['published_by']
    for item in a['items']:
        public = client.get(f"/api/v1/assignment-items/{item['id']}", headers=setup[2]).json()
        assert public['problem_version_id'] == item['problem_version_id']
        assert 'reference_solutions' not in public and 'test_cases' not in public
    changed = deepcopy(body); changed['title'] = '不能改写已发布内容'
    assert client.put(f"/api/v1/teacher/assignments/{a['id']}", headers=setup[0], json={'expected_updated_at':a['updated_at'],'assignment':changed}).status_code == 409
    assert publish(client, setup, a).status_code == 409
    assert db.scalar(select(func.count()).select_from(AssignmentParticipant).where(AssignmentParticipant.assignment_id==int(a['id']))) == 1


def test_assignment_stale_draft_invalid_configs_and_atomic_failures(client, setup, db):
    body = assignment_body(client, setup)
    a = create(client, setup, body)
    params = {'expected_updated_at': a['updated_at'], 'assignment': body}
    changed = client.put(f"/api/v1/teacher/assignments/{a['id']}", headers=setup[0], json=params)
    assert changed.status_code == 200
    assert client.put(f"/api/v1/teacher/assignments/{a['id']}", headers=setup[0], json=params).status_code == 409
    count = db.scalar(select(func.count()).select_from(Assignment))
    invalid = deepcopy(body); invalid['items'][0]['test_suite_id'] = '9223372036854775806'
    assert client.post(f'/api/v1/teacher/courses/{setup[1]}/assignments', headers=setup[0], json=invalid).status_code == 422
    assert db.scalar(select(func.count()).select_from(Assignment)) == count
    a = create(client, setup, body)
    assert all('score_weight' not in item for item in a['items'])
    assert publish(client, setup, a).status_code == 200
    assert client.post(f'/api/v1/teacher/courses/{setup[1]}/assignments', headers=setup[2], json=body).status_code == 403


def test_close_reopen_deadline_and_shared_candidate_progress(client, setup, db):
    a = create(client, setup, assignment_body(client, setup, mixed=True))
    a = publish(client, setup, a, 'CLOSED').json()
    subjective = next(i for i in a['items'] if i['question_type']!='PROGRAMMING')
    path = f"/api/v1/assignment-items/{subjective['id']}/submissions"
    def submit():
        return client.post(path, headers=setup[2], json={'client_request_id':str(uuid.uuid4()),'content':'合成推导','language':None})
    assert submit().status_code == 409
    params = {'expected_updated_at':a['updated_at'],'submission_deadline':a['submission_deadline'],'review_deadline':None,'submission_status':'OPEN'}
    response = client.post(f"/api/v1/teacher/assignments/{a['id']}/schedule", headers=setup[0], json=params)
    assert response.status_code == 200, response.text
    a = response.json(); assert submit().status_code == 202
    own = client.get(f'/api/v1/courses/{setup[1]}/my-progress', headers=setup[2]).json()
    shared = client.get(f"/api/v1/teacher/courses/{setup[1]}/students/{a['student_ids'][0]}/progress", headers=setup[0]).json()
    assert own['items'] == shared['items']
    params['expected_updated_at'] = a['updated_at']; params['submission_status'] = 'CLOSED'
    response = client.post(f"/api/v1/teacher/assignments/{a['id']}/schedule", headers=setup[0], json=params)
    assert response.status_code == 200 and submit().status_code == 409
    a = response.json(); params['expected_updated_at']=a['updated_at']; params['submission_status']='OPEN'
    params['submission_deadline']=(utcnow()-timedelta(days=1)).isoformat()
    assert client.post(f"/api/v1/teacher/assignments/{a['id']}/schedule", headers=setup[0], json=params).status_code == 422
    assert client.get(f"/api/v1/teacher/courses/{setup[1]}/students/{a['student_ids'][0]}/progress", headers=setup[2]).status_code == 403


def test_unsupported_node_cannot_open_but_can_publish_read_only(client, setup, monkeypatch):
    a = create(client, setup, assignment_body(client, setup))
    monkeypatch.setenv('JUDGE_EXECUTION_MODE', 'LINUX_SANDBOX')
    assert publish(client, setup, a).status_code == 422
    response = publish(client, setup, a, 'CLOSED')
    assert response.status_code == 200 and response.json()['submission_status'] == 'CLOSED'


def test_close_wins_while_submission_waits_on_assignment_lock(client, live_client, setup, db, monkeypatch):
    from sqlalchemy.orm import Session
    from app.student import service
    a = publish(client, setup, create(client, setup, assignment_body(client, setup))).json()
    item = a['items'][0]
    observed = threading.Event()
    original = service.item_context
    calls = 0
    def context(*args, **kwargs):
        nonlocal calls
        result = original(*args, **kwargs)
        calls += 1
        if calls == 1:
            observed.set()  # stale OPEN was read; acceptance must refresh after acquiring the lock
        return result
    monkeypatch.setattr(service, 'item_context', context)
    with Session(db.bind) as closing:
        locked = closing.scalar(select(Assignment).where(Assignment.id==int(a['id'])).with_for_update())
        locked.submission_status = 'CLOSED'; closing.flush()
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(live_client.post, f"/api/v1/assignment-items/{item['id']}/submissions", headers=setup[2],
                json={'client_request_id':str(uuid.uuid4()),'content':'print(1)','language':'python3'})
            seen = observed.wait(5)
            closing.commit()
            response = future.result(timeout=10)
            assert seen, "submission did not reach its refreshed item context"
    assert response.status_code == 409 and response.json()['code'] == 'SUBMISSION_CLOSED'
