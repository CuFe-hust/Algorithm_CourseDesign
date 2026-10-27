"""Teacher assignment lifecycle over shared, immutable question/configuration IDs."""
from decimal import Decimal

from sqlalchemy import delete, func, select

from app.common.permissions import require_teacher
from app.core.errors import AppError
from app.db.base import utcnow
from app.db.models import (Assignment, AssignmentItem, AssignmentParticipant, Class, CourseMember,
    Problem, ProblemVersion, Rubric, StudentProfile, TestSuite, User)
from app.student.service import iso
from app.teacher.problems import latest_config, validate_ready


def context(db, assignment_id, actor, *, lock=False):
    query = select(Assignment).where(Assignment.id == assignment_id)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    assignment = db.scalar(query)
    if assignment is None:
        raise AppError(404, 'NOT_FOUND', '作业不存在或不可访问')
    require_teacher(db, assignment.course_id, actor.id)
    return assignment


def check_revision(assignment, expected):
    if assignment.updated_at != expected:
        raise AppError(409, 'ASSIGNMENT_CONFLICT', '作业已被其他页面修改，请重新载入')


def item_rows(db, assignment):
    return list(db.scalars(select(AssignmentItem).where(AssignmentItem.assignment_id == assignment.id)
                           .order_by(AssignmentItem.sort_order)))


def validate_items(db, course_id, items, *, publishing=False, check_node=False, allow_archived=False):
    if publishing and (not items):
        raise AppError(422, 'EMPTY_ASSIGNMENT_ITEMS', '发布需至少一道题')
    for item in items:
        version = db.get(ProblemVersion, item.problem_version_id)
        problem = db.get(Problem, version.problem_id) if version else None
        if version is None or problem is None or problem.course_id != course_id:
            raise AppError(422, 'INVALID_ASSIGNMENT_CONFIGURATION', '题目必须属于当前课程')
        if version.status != 'FROZEN' or (problem.status != 'ACTIVE' and not allow_archived):
            raise AppError(422, 'INVALID_ASSIGNMENT_CONFIGURATION', '请选择在用题目的已冻结版本')
        programming = problem.question_type == 'PROGRAMMING'
        if (programming and (not item.test_suite_id or item.rubric_id or item.required_reviewers != 0)
                or not programming and (not item.rubric_id or item.test_suite_id or item.required_reviewers <= 0)):
            raise AppError(422, 'INVALID_ASSIGNMENT_CONFIGURATION', '编程题需测试集，主观题需量表和评审人数')
        config = db.get(TestSuite if programming else Rubric,
                        item.test_suite_id if programming else item.rubric_id)
        if config is None or config.problem_version_id != version.id or config.status != 'FROZEN':
            raise AppError(422, 'INVALID_ASSIGNMENT_CONFIGURATION', '测试集或量表必须属于同一题目版本且已冻结')
        if publishing:
            validate_ready(db, problem, version, suite_id=item.test_suite_id,
                           rubric_id=item.rubric_id, check_node=check_node)


def roster(db, course_id, student_ids, *, lock=False):
    statement = (select(User, StudentProfile, Class).join(StudentProfile, StudentProfile.user_id == User.id)
        .join(Class, Class.id == StudentProfile.class_id).join(CourseMember, CourseMember.user_id == User.id)
        .where(User.id.in_(student_ids), User.status.in_(['PENDING', 'ACTIVE']), Class.status == 'ACTIVE',
            CourseMember.course_id == course_id, CourseMember.role == 'STUDENT', CourseMember.status == 'ACTIVE')
        .order_by(User.id))
    if lock:
        statement = statement.with_for_update(of=[User, StudentProfile, Class, CourseMember])
    rows = db.execute(statement.execution_options(populate_existing=True)).all()
    if {u.id for u, _, _ in rows} != set(student_ids):
        raise AppError(422, 'INVALID_ASSIGNMENT_ROSTER', '应交学生需为本课程有效学生且已分配有效班级')
    return rows


def view(db, assignment):
    rows = db.execute(select(AssignmentItem, ProblemVersion, Problem)
        .join(ProblemVersion, ProblemVersion.id == AssignmentItem.problem_version_id)
        .join(Problem, Problem.id == ProblemVersion.problem_id)
        .where(AssignmentItem.assignment_id == assignment.id).order_by(AssignmentItem.sort_order)).all()
    people = db.execute(select(AssignmentParticipant, User).join(User, User.id == AssignmentParticipant.student_id)
        .where(AssignmentParticipant.assignment_id == assignment.id).order_by(User.student_no, User.id)).all()
    return {'id': str(assignment.id), 'course_id': str(assignment.course_id), 'title': assignment.title,
        'description_md': assignment.description_md, 'submission_status': assignment.submission_status,
        'submission_deadline': iso(assignment.submission_deadline), 'review_deadline': iso(assignment.review_deadline),
        'updated_at': iso(assignment.updated_at), 'published_at': iso(assignment.published_at),
        'published_by': str(assignment.published_by) if assignment.published_by else None,
        'items': [{'id': str(i.id), 'problem_version_id': str(v.id), 'problem_id': str(p.id),
            'code': p.code, 'title': v.title, 'question_type': p.question_type, 'version_no': v.version_no,
            'test_suite_id': str(i.test_suite_id) if i.test_suite_id else None,
            'rubric_id': str(i.rubric_id) if i.rubric_id else None,
            'max_score': str(i.max_score),
            'required_reviewers': i.required_reviewers} for i, v, p in rows],
        'student_ids': [str(p.student_id) for p, _ in people],
        'participants': [{'student_id': str(p.student_id), 'student_no': u.student_no,
            'full_name': u.full_name, 'status': u.status, 'class_name_at_publish': p.class_name_at_publish}
            for p, u in people]}


def list_assignments(db, course_id, actor, limit, offset):
    require_teacher(db, course_id, actor.id)
    query = select(Assignment).where(Assignment.course_id == course_id)
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = list(db.scalars(query.order_by(Assignment.id.desc()).limit(limit).offset(offset)))
    return {'total': total, 'limit': limit, 'offset': offset, 'items': [
        {'id': str(a.id), 'title': a.title, 'submission_status': a.submission_status,
         'submission_deadline': iso(a.submission_deadline), 'updated_at': iso(a.updated_at),
         'item_count': db.scalar(select(func.count()).select_from(AssignmentItem).where(AssignmentItem.assignment_id == a.id)),
         'participant_count': db.scalar(select(func.count()).select_from(AssignmentParticipant).where(AssignmentParticipant.assignment_id == a.id))}
        for a in rows]}


def replace_draft(db, assignment, body):
    validate_items(db, assignment.course_id, body.items)
    people = roster(db, assignment.course_id, body.student_ids)
    assignment.title = body.title.strip()
    assignment.description_md = body.description_md
    assignment.submission_deadline = body.submission_deadline
    assignment.review_deadline = body.review_deadline
    assignment.updated_at = utcnow()
    db.flush()
    db.execute(delete(AssignmentItem).where(AssignmentItem.assignment_id == assignment.id))
    db.execute(delete(AssignmentParticipant).where(AssignmentParticipant.assignment_id == assignment.id))
    for order, item in enumerate(body.items):
        db.add(AssignmentItem(assignment_id=assignment.id, sort_order=order, **item.model_dump()))
    for user, _, cls in people:
        db.add(AssignmentParticipant(assignment_id=assignment.id, student_id=user.id,
            class_id_at_publish=cls.id, class_name_at_publish=cls.name))
    db.flush()
    return view(db, assignment)


def create(db, course_id, actor, body):
    require_teacher(db, course_id, actor.id)
    assignment = Assignment(course_id=course_id, title=body.title,
        submission_deadline=body.submission_deadline, created_by=actor.id)
    db.add(assignment)
    db.flush()
    return replace_draft(db, assignment, body)


def update(db, assignment_id, actor, body):
    assignment = context(db, assignment_id, actor, lock=True)
    check_revision(assignment, body.expected_updated_at)
    if assignment.submission_status != 'DRAFT':
        raise AppError(409, 'ASSIGNMENT_PUBLISHED', '发布后不可改写题目、分值或应交名单；请创建新作业')
    return replace_draft(db, assignment, body.assignment)


def publish(db, assignment_id, actor, body):
    assignment = context(db, assignment_id, actor, lock=True)
    check_revision(assignment, body.expected_updated_at)
    if assignment.submission_status != 'DRAFT':
        raise AppError(409, 'ASSIGNMENT_PUBLISHED', '作业已经发布，请使用截止和开关管理')
    if assignment.submission_deadline <= utcnow():
        raise AppError(422, 'INVALID_DEADLINE', '发布时提交截止必须在未来')
    validate_items(db, assignment.course_id, item_rows(db, assignment), publishing=True,
                   check_node=body.submission_status == 'OPEN')
    participants = list(db.scalars(select(AssignmentParticipant).where(
        AssignmentParticipant.assignment_id == assignment.id)))
    if not participants:
        raise AppError(422, 'EMPTY_ASSIGNMENT_ROSTER', '发布前至少选择一位应交学生')
    people = roster(db, assignment.course_id, [p.student_id for p in participants], lock=True)
    classes = {u.id: cls for u, _, cls in people}
    for participant in participants:
        participant.class_id_at_publish = classes[participant.student_id].id
        participant.class_name_at_publish = classes[participant.student_id].name
    assignment.published_by = actor.id
    assignment.published_at = utcnow()
    assignment.submission_status = body.submission_status
    assignment.updated_at = utcnow()
    db.flush()
    return view(db, assignment)


def schedule(db, assignment_id, actor, body):
    assignment = context(db, assignment_id, actor, lock=True)
    check_revision(assignment, body.expected_updated_at)
    if assignment.submission_status == 'DRAFT':
        raise AppError(409, 'ASSIGNMENT_DRAFT', '请先保存并发布草稿')
    if (body.submission_deadline <= assignment.published_at
            or body.review_deadline is not None and body.review_deadline <= body.submission_deadline):
        raise AppError(422, 'INVALID_DEADLINE', '截止需晚于发布时间，评审截止需晚于提交截止')
    if body.submission_status == 'OPEN':
        if body.submission_deadline <= utcnow():
            raise AppError(422, 'INVALID_DEADLINE', '开放提交时截止必须在未来')
        validate_items(db, assignment.course_id, item_rows(db, assignment), publishing=True, check_node=True,
                       allow_archived=True)
    assignment.submission_deadline = body.submission_deadline
    assignment.review_deadline = body.review_deadline
    assignment.submission_status = body.submission_status
    assignment.updated_at = utcnow()
    db.flush()
    return view(db, assignment)


def choices(db, course_id, actor, limit, offset, q):
    require_teacher(db, course_id, actor.id)
    query = select(ProblemVersion, Problem).join(Problem, Problem.id == ProblemVersion.problem_id).where(
        Problem.course_id == course_id, Problem.status == 'ACTIVE', ProblemVersion.status == 'FROZEN')
    if q:
        pattern = '%' + q.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
        query = query.where(ProblemVersion.title.ilike(pattern, escape='\\') | Problem.code.ilike(pattern, escape='\\'))
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.execute(query.order_by(Problem.id, ProblemVersion.version_no.desc()).limit(limit).offset(offset)).all()
    items = []
    for version, problem in rows:
        suite = latest_config(db, TestSuite, version.id)
        rubric = latest_config(db, Rubric, version.id)
        items.append({'problem_version_id': str(version.id), 'code': problem.code, 'title': version.title,
            'version_no': version.version_no, 'question_type': problem.question_type,
            'test_suite_id': str(suite.id) if suite else None, 'rubric_id': str(rubric.id) if rubric else None})
    return {'items': items, 'total': total, 'limit': limit, 'offset': offset}
