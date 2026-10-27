import hashlib
import pytest
from sqlalchemy import select, func
from app.db.models import User, Class, Course, CourseMember, StudentProfile
from app.teacher import students


@pytest.fixture
def teacher(demo, auth):
    return auth('demo.teacher'), demo[0]['course_id']


def preview(client, teacher, raw):
    headers, course = teacher
    return client.post(f'/api/v1/teacher/courses/{course}/students/import/preview', headers=headers, files={'file': ('roster.csv', raw, 'text/csv')})


def confirm(client, teacher, raw, data, **options):
    headers, course = teacher
    return client.post(f'/api/v1/teacher/courses/{course}/students/import/confirm', headers=headers,
        files={'file': ('roster.csv', raw, 'text/csv')}, data={
            'expected_sha256': data['content_sha256'], 'preview_token': data['preview_token'], **options})


def test_preview_readonly_confirm_pending_idempotent_and_template(client, teacher, db):
    headers, course = teacher
    raw = 'student_no,full_name,class_name\r\n000012,合成学生甲,合成一班\r\n000013,合成学生乙,合成一班\r\n'.encode('utf-8-sig')
    count = db.scalar(select(func.count()).select_from(User))
    result = preview(client, teacher, raw)
    assert result.status_code == 200, result.text
    data = result.json(); assert data['valid'] is True
    assert data['summary']['created_students'] == 2 and data['summary']['created_classes'] == 1
    assert db.scalar(select(func.count()).select_from(User)) == count
    uploaded = confirm(client, teacher, raw, data)
    assert uploaded.status_code == 200, uploaded.text
    user = db.scalar(select(User).where(User.student_no == '000012'))
    assert user.login_name == '000012' and user.status == 'PENDING' and user.password_hash is None
    assert confirm(client, teacher, raw, data).json()['replayed'] is True
    assert db.scalar(select(func.count()).select_from(User)) == count + 2
    listing = client.get(f'/api/v1/teacher/courses/{course}/students?q=00001', headers=headers)
    assert listing.status_code == 200, listing.text
    assert listing.json()['total'] == 2 and isinstance(listing.json()['items'][0]['id'], str)
    assert client.get(f'/api/v1/teacher/courses/{course}/classes', headers=headers).status_code == 200
    template = client.get(f'/api/v1/teacher/courses/{course}/students/import/template', headers=headers)
    assert template.status_code == 200 and template.content.startswith(b'\xef\xbb\xbf')


@pytest.mark.parametrize('raw', [b'', b'bad,headers\n1,2', b'\xff', b'student_no,full_name,class_name\n',
    b'student_no,full_name,class_name\n' + b'a' * (2 * 1024 * 1024),
    ('student_no,full_name,class_name\n' + '\n'.join(f'{i},Test,Class' for i in range(2001))).encode()], ids=['empty','headers','encoding','no-rows','file-too-large','too-many-rows'])
def test_invalid_csv_rejected(client, teacher, raw):
    assert preview(client, teacher, raw).status_code == 422


@pytest.mark.parametrize('lines', [
    '001,甲,一班\n001,甲,一班', '001,,一班', '001,甲,一班,EXTRA', 'ABC,甲,一班\nabc,乙,一班',
])
def test_row_errors_block_entire_import(client, teacher, db, lines):
    raw = ('student_no,full_name,class_name\n' + lines).encode()
    data = preview(client, teacher, raw).json()
    assert data['valid'] is False and data['preview_token'] is None
    assert any(row['errors'] for row in data['rows'])
    assert db.scalar(select(User.id).where(User.student_no == '001')) is None


def test_existing_update_requires_confirmation_and_cross_course_is_blocked(client, teacher, db):
    headers, course = teacher
    user = db.scalar(select(User).where(User.login_name == 'demo.student01'))
    profile = db.scalar(select(StudentProfile).where(StudentProfile.user_id == user.id))
    cls = db.get(Class, profile.class_id)
    raw = f'student_no,full_name,class_name,class_code\n{user.student_no},新合成姓名,{cls.name},{cls.class_code}'.encode()
    before = user.password_hash
    data = preview(client, teacher, raw).json()
    assert data['valid'] is True and data['requires_update_confirmation'] is True
    assert confirm(client, teacher, raw, data).status_code == 409
    assert confirm(client, teacher, raw, data, allow_updates='true').status_code == 200
    db.refresh(user); assert user.full_name == '新合成姓名' and user.password_hash == before and user.status == 'ACTIVE'
    other = Course(code='OTHER', name='其他课', term='2026', created_by=user.id); db.add(other); db.flush()
    db.add(CourseMember(course_id=other.id, user_id=user.id, role='STUDENT')); db.commit()
    raw = raw.replace('新合成姓名'.encode(), '再次修改姓名'.encode())
    assert preview(client, teacher, raw).json()['valid'] is False
    assert user.full_name == '新合成姓名'


def test_stale_tampered_expired_and_wrong_actor_preview(client, teacher, db, auth, monkeypatch):
    raw = 'student_no,full_name,class_name\n00991,甲,新一班'.encode()
    data = preview(client, teacher, raw).json()
    changed = raw.replace(b'00991', b'00992')
    assert confirm(client, teacher, changed, data).status_code == 409
    assert confirm(client, teacher, raw, {**data, 'preview_token': data['preview_token']+'x'}).status_code == 409
    cls = Class(class_code='NEW-C', name='新一班'); db.add(cls); db.commit()
    result = confirm(client, teacher, raw, data)
    assert result.status_code == 409 and result.json()['code'] == 'PREVIEW_STALE'
    data = preview(client, teacher, raw).json()
    monkeypatch.setattr(students.time, 'time', lambda: 99999999999)
    assert confirm(client, teacher, raw, data).status_code == 409
    student_headers = auth()
    assert preview(client, (student_headers, teacher[1]), raw).status_code == 403
    assert db.scalar(select(User.id).where(User.student_no == '00991')) is None


def test_ambiguous_class_and_role_conflict(client, teacher, db):
    db.add_all([Class(class_code='C-1', name='同名班'), Class(class_code='C-2', name='同名班')]); db.commit()
    raw = 'student_no,full_name,class_name\n0999,甲,同名班'.encode()
    assert not preview(client, teacher, raw).json()['valid']
    raw = 'student_no,full_name,class_name,class_code\n0999,甲,同名班,C-1'.encode()
    assert preview(client, teacher, raw).json()['valid']
    teacher_user = db.scalar(select(User).where(User.login_name == 'demo.teacher'))
    teacher_user.student_no = 'TEACHER'; db.commit()
    raw = f'student_no,full_name,class_name\nTEACHER,{teacher_user.full_name},同名班'.encode()
    assert not preview(client, teacher, raw).json()['valid']


def test_concurrent_confirm_creates_single_identity_and_membership(db, demo):
    from concurrent.futures import ThreadPoolExecutor
    from sqlalchemy.orm import Session
    actor_id = db.scalar(select(User.id).where(User.login_name == 'demo.teacher'))
    course_id = int(demo[0]['course_id'])
    raw = 'student_no,full_name,class_name\nCONCURRENT-01,合成并发学生,合成并发班'.encode()
    actor = db.get(User, actor_id)
    data = students.preview_import(db, course_id, actor, raw)
    db.commit()
    def run(_):
        with Session(db.bind, expire_on_commit=False) as session:
            result = students.confirm_import(session, course_id, session.get(User, actor_id), raw,
                data['content_sha256'], data['preview_token'], False)
            session.commit()
            return result
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(run, range(4)))
    assert sum(not r['replayed'] for r in results) == 1
    assert db.scalar(select(func.count()).select_from(User).where(User.student_no == 'CONCURRENT-01')) == 1
    user_id = db.scalar(select(User.id).where(User.student_no == 'CONCURRENT-01'))
    assert db.scalar(select(func.count()).select_from(CourseMember).where(CourseMember.course_id == course_id, CourseMember.user_id == user_id)) == 1


def test_failure_during_confirm_rolls_back_whole_batch(client, teacher, db):
    from sqlalchemy import event
    raw = 'student_no,full_name,class_name\nFAIL-01,合成甲,合成失败班\nFAIL-02,合成乙,合成失败班'.encode()
    data = preview(client, teacher, raw).json()
    def fail(mapper, connection, target):
        if target.login_name == 'fail-02':
            raise RuntimeError('synthetic write failure')
    event.listen(User, 'before_insert', fail)
    try:
        response = confirm(client, teacher, raw, data)
    finally:
        event.remove(User, 'before_insert', fail)
    assert response.status_code == 500 and 'synthetic write failure' not in response.text
    assert db.scalar(select(User.id).where(User.student_no.in_(['FAIL-01', 'FAIL-02']))) is None
    assert db.scalar(select(Class.id).where(Class.name == '合成失败班')) is None
