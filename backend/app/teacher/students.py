"""Preview/confirm CSV import. Shared identities are never silently overwritten."""
from collections import Counter, defaultdict
from dataclasses import dataclass
import base64
import csv
import hashlib
import hmac
import io
import json
import re
import time

from sqlalchemy import func, or_, select, text

from app.common.permissions import require_teacher
from app.core.config import Settings
from app.core.errors import AppError
from app.db.models import Class, CourseMember, StudentProfile, User
from app.student.service import iso

MAX_CSV_BYTES = 2 * 1024 * 1024
MAX_ROWS = 2000
PREVIEW_SECONDS = 900
IMPORT_LOCK = 724654001
STUDENT_NO = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.-]{0,31}$')
CLASS_CODE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$')


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(',', ':')).encode()).hexdigest()


def read_roster(raw):
    if not raw or len(raw) > MAX_CSV_BYTES:
        raise AppError(422, 'INVALID_CSV_SIZE', '请上传非空且不超过 2 MiB 的 CSV 文件')
    try:
        content = raw.decode('utf-8-sig')
        if '\x00' in content:
            raise ValueError('NUL')
        reader = csv.DictReader(io.StringIO(content, newline=''), strict=True)
        headers = reader.fieldnames
        required = {'student_no', 'full_name', 'class_name'}
        if not headers or len(headers) != len(set(headers)) or not required <= set(headers) or set(headers) - required - {'class_code'}:
            raise AppError(422, 'INVALID_CSV_HEADERS',
                'CSV 必须包含 student_no、full_name、class_name，可选 class_code；不能有重复或额外列')
        rows = []
        for record in reader:
            if len(rows) >= MAX_ROWS:
                raise AppError(422, 'TOO_MANY_ROWS', '单次最多导入 2000 行，请拆分文件')
            fields = {name: (record.get(name) or '').strip() for name in headers}
            errors = []
            if None in record or any(record.get(name) is None for name in headers):
                errors.append('列数与表头不一致')
            if not STUDENT_NO.fullmatch(fields['student_no']):
                errors.append('学号应为 1 至 32 位文本，仅支持字母、数字、点、下划线和短横线')
            for name, label in [('full_name', '姓名'), ('class_name', '班级')]:
                if not fields[name] or len(fields[name]) > 100 or any(ord(c) < 32 for c in fields[name]):
                    errors.append(label + '不能为空，长度至多 100，且不能包含换行或控制字符')
            if fields.get('class_code') and not CLASS_CODE.fullmatch(fields['class_code']):
                errors.append('班级编码格式不正确')
            rows.append({**fields, 'row_number': reader.line_num, 'errors': errors})
    except (UnicodeDecodeError, csv.Error, ValueError):
        raise AppError(422, 'INVALID_CSV_ENCODING', '文件无法读取，请从 Excel 另存为 CSV UTF-8 格式')
    if not rows:
        raise AppError(422, 'EMPTY_ROSTER', 'CSV 只有表头，没有学生记录')
    duplicates = Counter(row['student_no'] for row in rows)
    for row in rows:
        if duplicates[row['student_no']] > 1:
            row['errors'].append('同一文件中学号重复；请保留一行后重新预览')
    return rows


@dataclass
class ImportPlan:
    rows: list
    classes: dict
    users: dict
    profiles: dict
    members: dict
    snapshot_hash: str
    summary: dict

    @property
    def valid(self):
        return all(not row['errors'] for row in self.rows)


def _query(db, statement, lock):
    if lock:
        statement = statement.with_for_update()
    return list(db.scalars(statement.execution_options(populate_existing=True)))


def build_plan(db, course_id, raw, *, lock=False):
    rows = read_roster(raw)
    names = {r['class_name'] for r in rows}
    codes = {r.get('class_code') or 'TCSV_' + hashlib.sha256(r['class_name'].encode()).hexdigest()[:24] for r in rows}
    class_rows = _query(db, select(Class).where(or_(Class.name.in_(names), Class.class_code.in_(codes)))
                        .order_by(Class.id), lock)
    classes = {c.class_code: c for c in class_rows}
    candidates = defaultdict(set)
    for cls in class_rows:
        candidates[cls.name].add(cls.class_code)
    declared = defaultdict(set)
    for row in rows:
        if row.get('class_code'):
            declared[row['class_code']].add(row['class_name'])
            candidates[row['class_name']].add(row['class_code'])
    numbers = {r['student_no'] for r in rows}
    logins = {number.casefold() for number in numbers}
    user_rows = _query(db, select(User).where(or_(User.student_no.in_(numbers), User.login_name.in_(logins)))
                       .order_by(User.id), lock)
    users = {u.student_no: u for u in user_rows if u.student_no in numbers}
    login_users = {u.login_name: u for u in user_rows}
    user_ids = [u.id for u in user_rows]
    profile_rows = _query(db, select(StudentProfile).where(StudentProfile.user_id.in_(user_ids))
                          .order_by(StudentProfile.id), lock)
    member_rows = _query(db, select(CourseMember).where(CourseMember.user_id.in_(user_ids))
                         .order_by(CourseMember.id), lock)
    profiles = {p.user_id: p for p in profile_rows}
    members = {(m.course_id, m.user_id): m for m in member_rows}
    memberships = defaultdict(list)
    for member in member_rows:
        memberships[member.user_id].append(member)
    # Capture the whole relevant read set, including absent/present class and login resolutions.
    snapshot = {
        'classes': [(c.id, c.class_code, c.name, c.status, iso(c.updated_at)) for c in class_rows],
        'users': [(u.id, u.login_name, u.student_no, u.full_name, u.status, iso(u.updated_at)) for u in user_rows],
        'profiles': [(p.user_id, p.class_id, iso(p.updated_at)) for p in profile_rows],
        'members': [(m.course_id, m.user_id, m.role, m.status, iso(m.updated_at)) for m in member_rows],
    }
    summary = dict(created_students=0, enrolled_students=0, updated_profiles=0, unchanged_students=0, created_classes=0)
    new_classes = set()
    for row in rows:
        code = row.get('class_code')
        if code and len(declared[code]) > 1:
            row['errors'].append('同一班级编码对应多个班名')
        if not code:
            options = candidates[row['class_name']]
            if len(options) > 1:
                row['errors'].append('班级名称不唯一，请填写 class_code 明确选择')
            code = next(iter(options)) if len(options) == 1 else 'TCSV_' + hashlib.sha256(row['class_name'].encode()).hexdigest()[:24]
        row['resolved_class_code'] = code
        cls = classes.get(code)
        if cls and (cls.name != row['class_name'] or cls.status != 'ACTIVE'):
            row['errors'].append('班级编码与名称不一致，或班级已经停用')
        user = users.get(row['student_no'])
        member = members.get((course_id, user.id)) if user else None
        profile = profiles.get(user.id) if user else None
        changes = []
        if user:
            if member and member.role != 'STUDENT':
                row['errors'].append('该账号在当前课程不是学生，不能通过名册改变课程角色')
            if user.full_name != row['full_name']:
                changes.append('姓名')
            if profile is None or cls is None or profile.class_id != cls.id:
                changes.append('班级')
            if changes:
                outside = any(m.course_id != course_id and m.status == 'ACTIVE' for m in memberships[user.id])
                if not member or member.role != 'STUDENT' or outside:
                    row['errors'].append('现有共享身份资料不一致，或关联其他课程；请由数据库负责人核对后更新')
            action = 'UPDATE' if changes else ('ENROLL' if not member or member.status != 'ACTIVE' else 'UNCHANGED')
        else:
            other = login_users.get(row['student_no'].casefold())
            if other is not None:
                row['errors'].append('学号对应的登录名已被其他账号占用')
            action = 'CREATE'
        row['action'] = 'ERROR' if row['errors'] else action
        row['changes'] = changes
        if row['errors']:
            continue
        if cls is None:
            new_classes.add(code)
        if user is None:
            summary['created_students'] += 1
        if member is None or member.status != 'ACTIVE':
            summary['enrolled_students'] += 1
        if changes:
            summary['updated_profiles'] += 1
        if action == 'UNCHANGED':
            summary['unchanged_students'] += 1
    # Different case-sensitive student numbers must not create the same canonical login.
    new_logins = Counter(r['student_no'].casefold() for r in rows if r['student_no'] not in users)
    for row in rows:
        if row['student_no'] not in users and new_logins[row['student_no'].casefold()] > 1:
            row['errors'].append('新账号登录名不区分字母大小写，同批学号产生冲突')
            row['action'] = 'ERROR'
    summary['created_classes'] = len(new_classes)
    return ImportPlan(rows, classes, users, profiles, members, digest(snapshot), summary)


def make_preview_token(course_id, actor_id, content_hash, snapshot_hash):
    payload = {'course': course_id, 'actor': actor_id, 'file': content_hash,
               'snapshot': snapshot_hash, 'expires': int(time.time()) + PREVIEW_SECONDS}
    encoded = base64.urlsafe_b64encode(json.dumps(payload, sort_keys=True, separators=(',', ':')).encode()).decode().rstrip('=')
    signature = hmac.new(Settings.load().secret.encode(), encoded.encode(), hashlib.sha256).hexdigest()
    return encoded + '.' + signature


def verify_preview_token(token, course_id, actor_id, content_hash):
    try:
        if len(token) > 2048:
            raise ValueError()
        encoded, signature = token.split('.')
        expected = hmac.new(Settings.load().secret.encode(), encoded.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature):
            raise ValueError()
        payload = json.loads(base64.urlsafe_b64decode(encoded + '=' * (-len(encoded) % 4)))
        if (payload['course'], payload['actor'], payload['file']) != (course_id, actor_id, content_hash):
            raise ValueError()
        if payload['expires'] <= int(time.time()):
            raise ValueError()
        return payload['snapshot']
    except (ValueError, KeyError, TypeError, UnicodeError):
        raise AppError(409, 'PREVIEW_EXPIRED', '预览已过期或与当前文件、教师、课程不一致，请重新预览')


def preview_import(db, course_id, user, raw):
    require_teacher(db, course_id, user.id)
    plan = build_plan(db, course_id, raw)
    content_hash = hashlib.sha256(raw).hexdigest()
    return {
        'valid': plan.valid, 'content_sha256': content_hash, 'summary': plan.summary,
        'rows': plan.rows, 'requires_update_confirmation': bool(plan.summary['updated_profiles']),
        'preview_token': make_preview_token(course_id, user.id, content_hash, plan.snapshot_hash) if plan.valid else None,
        'expires_in': PREVIEW_SECONDS,
    }


def confirm_import(db, course_id, user, raw, expected_sha256, preview_token, allow_updates):
    require_teacher(db, course_id, user.id)
    content_hash = hashlib.sha256(raw).hexdigest()
    if not hmac.compare_digest(content_hash, expected_sha256):
        raise AppError(409, 'FILE_CHANGED', '文件内容与预览不一致，请重新预览')
    previous_snapshot = verify_preview_token(preview_token, course_id, user.id, content_hash)
    # Import touches globally unique identities/classes, not only one course's rows.
    db.execute(text('SELECT pg_advisory_xact_lock(:key)'), {'key': IMPORT_LOCK})
    plan = build_plan(db, course_id, raw, lock=True)
    if not plan.valid:
        raise AppError(409, 'ROSTER_CONFLICT', '名册或数据库状态存在冲突，请重新预览', {'rows': plan.rows})
    unchanged = all(row['action'] == 'UNCHANGED' for row in plan.rows)
    if previous_snapshot != plan.snapshot_hash:
        if unchanged:
            return {'status': 'imported', 'replayed': True, 'content_sha256': content_hash,
                    'summary': plan.summary, 'rows': len(plan.rows)}
        raise AppError(409, 'PREVIEW_STALE', '数据库资料在预览后已变化，请重新预览确认')
    if plan.summary['updated_profiles'] and not allow_updates:
        raise AppError(409, 'UPDATE_CONFIRMATION_REQUIRED', '请明确确认本课程已有学生的姓名或班级更新')
    for row in plan.rows:
        code = row['resolved_class_code']
        cls = plan.classes.get(code)
        if cls is None:
            cls = Class(class_code=code, name=row['class_name'])
            db.add(cls)
            db.flush()
            plan.classes[code] = cls
        user_record = plan.users.get(row['student_no'])
        if user_record is None:
            user_record = User(login_name=row['student_no'].casefold(), student_no=row['student_no'],
                               full_name=row['full_name'], status='PENDING', password_hash=None)
            db.add(user_record)
            db.flush()
            plan.users[row['student_no']] = user_record
        elif row['changes']:
            user_record.full_name = row['full_name']
        profile = plan.profiles.get(user_record.id)
        if profile is None:
            profile = StudentProfile(user_id=user_record.id, class_id=cls.id)
            db.add(profile)
            plan.profiles[user_record.id] = profile
        elif row['changes']:
            profile.class_id = cls.id
        member = plan.members.get((course_id, user_record.id))
        if member is None:
            member = CourseMember(course_id=course_id, user_id=user_record.id, role='STUDENT', status='ACTIVE')
            db.add(member)
            plan.members[(course_id, user_record.id)] = member
        else:
            member.status = 'ACTIVE'
    db.flush()
    return {'status': 'imported', 'replayed': unchanged, 'content_sha256': content_hash,
            'summary': plan.summary, 'rows': len(plan.rows)}


def list_students(db, course_id, user, query, class_id, limit, offset):
    require_teacher(db, course_id, user.id)
    statement = select(User, StudentProfile, Class).join(CourseMember, CourseMember.user_id == User.id)
    statement = statement.outerjoin(StudentProfile, StudentProfile.user_id == User.id)
    statement = statement.outerjoin(Class, Class.id == StudentProfile.class_id)
    statement = statement.where(CourseMember.course_id == course_id, CourseMember.role == 'STUDENT',
                                 CourseMember.status == 'ACTIVE')
    if query:
        pattern = '%' + query.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
        statement = statement.where(User.full_name.ilike(pattern, escape='\\') | User.student_no.ilike(pattern, escape='\\'))
    if class_id:
        statement = statement.where(StudentProfile.class_id == class_id)
    total = db.scalar(select(func.count()).select_from(statement.subquery()))
    rows = db.execute(statement.order_by(User.student_no, User.id).limit(limit).offset(offset)).all()
    return {'total': total, 'limit': limit, 'offset': offset, 'items': [
        {'id': str(u.id), 'student_no': u.student_no, 'full_name': u.full_name,
         'login_name': u.login_name, 'status': u.status, 'class_id': str(c.id) if c else None,
         'class_name': c.name if c else None, 'class_code': c.class_code if c else None}
        for u, _, c in rows]}


def list_classes(db, course_id, user):
    require_teacher(db, course_id, user.id)
    statement = select(Class).join(StudentProfile, StudentProfile.class_id == Class.id)
    statement = statement.join(CourseMember, CourseMember.user_id == StudentProfile.user_id)
    statement = statement.where(CourseMember.course_id == course_id, CourseMember.role == 'STUDENT',
                                 CourseMember.status == 'ACTIVE').distinct().order_by(Class.name, Class.id)
    return {'items': [{'id': str(c.id), 'code': c.class_code, 'name': c.name} for c in db.scalars(statement)]}
