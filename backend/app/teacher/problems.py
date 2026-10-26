"""Versioned authoring over the existing 21-table shared database."""
from decimal import Decimal
import hashlib

from sqlalchemy import delete, func, select

from app.common.permissions import require_teacher
from app.core.errors import AppError
from app.db.base import utcnow
from app.db.models import (
    AssignmentItem, KnowledgePoint, Problem, ProblemVersion, ProblemVersionTag,
    ReferenceSolution, Rubric, RubricItem, TestCase, TestSuite,
)
from app.student.service import iso
from app.teacher.schemas import VersionInput
from app.judge import config as judge_config

VERSION_FIELDS = (
    'title', 'statement_md', 'answer_requirements_md', 'input_spec_md',
    'output_spec_md', 'data_constraints_md', 'public_examples_md',
    'difficulty_level', 'source_reference',
)


def problem_context(db, problem_id, user, *, lock=False):
    query = select(Problem).where(Problem.id == problem_id)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    problem = db.scalar(query)
    if problem is None:
        raise AppError(404, 'NOT_FOUND', '题目不存在或不可访问')
    require_teacher(db, problem.course_id, user.id)
    return problem


def version_context(db, version_id, user, *, lock=False):
    version = db.get(ProblemVersion, version_id)
    if version is None:
        raise AppError(404, 'NOT_FOUND', '题目版本不存在或不可访问')
    problem = problem_context(db, version.problem_id, user, lock=lock)
    if lock:
        version = db.scalar(select(ProblemVersion).where(ProblemVersion.id == version_id)
                            .with_for_update().execution_options(populate_existing=True))
    return problem, version


def latest_config(db, model, version_id):
    return db.scalar(select(model).where(model.problem_version_id == version_id)
                     .order_by(model.version_no.desc()).limit(1))


def version_view(db, problem, version):
    tags = db.execute(select(KnowledgePoint, ProblemVersionTag.mastery_weight)
        .join(ProblemVersionTag, ProblemVersionTag.knowledge_point_id == KnowledgePoint.id)
        .where(ProblemVersionTag.problem_version_id == version.id).order_by(KnowledgePoint.id)).all()
    references = list(db.scalars(select(ReferenceSolution).where(
        ReferenceSolution.problem_version_id == version.id).order_by(ReferenceSolution.id)))
    suite = latest_config(db, TestSuite, version.id)
    rubric = latest_config(db, Rubric, version.id)
    cases = list(db.scalars(select(TestCase).where(TestCase.test_suite_id == suite.id)
                           .order_by(TestCase.sort_order))) if suite else []
    dimensions = list(db.scalars(select(RubricItem).where(RubricItem.rubric_id == rubric.id)
                                .order_by(RubricItem.sort_order))) if rubric else []
    return {
        'id': str(version.id), 'problem_id': str(problem.id), 'course_id': str(problem.course_id),
        'code': problem.code, 'question_type': problem.question_type, 'problem_status': problem.status,
        'version_no': version.version_no, 'status': version.status,
        'updated_at': iso(version.updated_at), 'frozen_at': iso(version.frozen_at),
        **{field: getattr(version, field) for field in VERSION_FIELDS},
        'knowledge_point_ids': [str(tag.id) for tag, _ in tags],
        'knowledge_points': [{'id': str(tag.id), 'name': tag.name, 'mastery_weight': str(weight)}
                             for tag, weight in tags],
        'reference_solutions': [{'id': str(ref.id), 'language': ref.language, 'content': ref.content}
                                for ref in references],
        'test_suite': {
            'id': str(suite.id), 'version_no': suite.version_no, 'cpu_limit_ms': suite.cpu_limit_ms,
            'memory_limit_kib': suite.memory_limit_kib, 'allowed_languages': suite.allowed_languages,
            'checker': suite.checker,
            'total_budget_ms': suite.total_budget_ms,
            'cases': [{'input_text': case.input_text, 'expected_output': case.expected_output,
                       'weight': str(case.weight), 'is_public': case.is_public} for case in cases],
        } if suite else None,
        'rubric': {'id': str(rubric.id), 'name': rubric.name,
                   'items': [{'name': dim.name, 'description': dim.description,
                              'max_score': str(dim.max_score)} for dim in dimensions]} if rubric else None,
    }


def list_problems(db, course_id, user, query, question_type, status, limit, offset):
    require_teacher(db, course_id, user.id)
    latest = select(ProblemVersion.problem_id, func.max(ProblemVersion.version_no).label('last'))
    latest = latest.group_by(ProblemVersion.problem_id).subquery()
    statement = select(Problem, ProblemVersion).join(latest, latest.c.problem_id == Problem.id)
    statement = statement.join(ProblemVersion, (ProblemVersion.problem_id == Problem.id)
                               & (ProblemVersion.version_no == latest.c.last))
    statement = statement.where(Problem.course_id == course_id)
    if query:
        pattern = '%' + query.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
        statement = statement.where(Problem.code.ilike(pattern, escape='\\')
                                    | ProblemVersion.title.ilike(pattern, escape='\\'))
    if question_type:
        statement = statement.where(Problem.question_type == question_type)
    if status:
        statement = statement.where(Problem.status == status)
    total = db.scalar(select(func.count()).select_from(statement.subquery()))
    rows = db.execute(statement.order_by(Problem.updated_at.desc(), Problem.id.desc())
                      .limit(limit).offset(offset)).all()
    return {'total': total, 'limit': limit, 'offset': offset, 'items': [
        {'id': str(p.id), 'code': p.code, 'question_type': p.question_type, 'status': p.status,
         'latest_version_id': str(v.id), 'version_no': v.version_no, 'version_status': v.status,
         'title': v.title, 'difficulty_level': v.difficulty_level, 'updated_at': iso(v.updated_at)}
        for p, v in rows]}


def verify_payload(db, problem, payload):
    if problem.question_type == 'PROGRAMMING' and payload.rubric is not None:
        raise AppError(422, 'WRONG_CONFIGURATION', '编程题不能配置主观评分量表')
    if problem.question_type != 'PROGRAMMING' and payload.test_suite is not None:
        raise AppError(422, 'WRONG_CONFIGURATION', '主观题不能配置编程测试集')
    if payload.knowledge_point_ids:
        found = set(db.scalars(select(KnowledgePoint.id).where(
            KnowledgePoint.id.in_(payload.knowledge_point_ids),
            KnowledgePoint.course_id == problem.course_id, KnowledgePoint.status == 'ACTIVE')))
        if found != set(payload.knowledge_point_ids):
            raise AppError(422, 'INVALID_KNOWLEDGE_POINT', '知识点必须属于当前课程且处于启用状态')


def write_configuration(db, problem, version, payload, actor_id):
    verify_payload(db, problem, payload)
    for model, config in ((TestSuite, payload.test_suite), (Rubric, payload.rubric)):
        if config is None and latest_config(db, model, version.id) is not None:
            raise AppError(422, 'CONFIGURATION_REQUIRED', '已有配置不可设为 null；清空草稿中的测试点或评分维度后保存')
    for field in VERSION_FIELDS:
        setattr(version, field, getattr(payload, field))
    version.updated_at = utcnow()
    # Only children of an editable, unpublished version are replaced.
    db.execute(delete(ProblemVersionTag).where(ProblemVersionTag.problem_version_id == version.id))
    db.execute(delete(ReferenceSolution).where(ReferenceSolution.problem_version_id == version.id))
    count = len(payload.knowledge_point_ids)
    if count:
        weights = [(Decimal(1) / count).quantize(Decimal('.000001'))] * count
        weights[-1] = Decimal(1) - sum(weights[:-1])
        for tag_id, weight in zip(payload.knowledge_point_ids, weights):
            db.add(ProblemVersionTag(problem_version_id=version.id, knowledge_point_id=tag_id,
                                     mastery_weight=weight))
    for ref in payload.reference_solutions:
        db.add(ReferenceSolution(problem_version_id=version.id, language=ref.language,
                                  content=ref.content, created_by=actor_id))
    now = utcnow()
    # Existing FROZEN suites/rubrics are immutable snapshots even when their parent is a draft.
    # Save a new configuration revision, rather than changing a snapshot in place.
    if payload.test_suite is not None:
        body = payload.test_suite
        previous = latest_config(db, TestSuite, version.id)
        suite = TestSuite(problem_version_id=version.id,
            version_no=previous.version_no + 1 if previous else 1, cpu_limit_ms=body.cpu_limit_ms,
            memory_limit_kib=body.memory_limit_kib, allowed_languages=body.allowed_languages,
            checker=body.checker, total_budget_ms=body.total_budget_ms if body.total_budget_ms is not None
                else min(3600000, judge_config.minimum_total_budget_ms(body.cpu_limit_ms, len(body.cases))), frozen_at=now)
        db.add(suite)
        db.flush()
        for order, case in enumerate(body.cases):
            db.add(TestCase(test_suite_id=suite.id, sort_order=order, **case.model_dump()))
    if payload.rubric is not None:
        body = payload.rubric
        previous = latest_config(db, Rubric, version.id)
        rubric = Rubric(problem_version_id=version.id, version_no=previous.version_no + 1 if previous else 1,
                         name=body.name, frozen_at=now)
        db.add(rubric)
        db.flush()
        for order, dimension in enumerate(body.items):
            db.add(RubricItem(rubric_id=rubric.id, sort_order=order, **dimension.model_dump()))
    db.flush()


def create_problem(db, course_id, user, body):
    require_teacher(db, course_id, user.id)
    if db.scalar(select(Problem.id).where(Problem.course_id == course_id, Problem.code == body.code)):
        raise AppError(409, 'PROBLEM_CODE_EXISTS', '当前课程已存在该题号，请使用其他题号')
    problem = Problem(course_id=course_id, code=body.code, question_type=body.question_type, created_by=user.id)
    db.add(problem)
    db.flush()
    version = ProblemVersion(problem_id=problem.id, version_no=1, created_by=user.id,
        title=body.version.title, statement_md=body.version.statement_md,
        difficulty_level=body.version.difficulty_level)
    db.add(version)
    db.flush()
    write_configuration(db, problem, version, body.version, user.id)
    return version_view(db, problem, version)


def ensure_editable(db, problem, version, expected):
    if problem.status != 'ACTIVE':
        raise AppError(409, 'PROBLEM_ARCHIVED', '请先恢复归档题目再编辑')
    if version.status != 'DRAFT' or db.scalar(select(AssignmentItem.id).where(
            AssignmentItem.problem_version_id == version.id).limit(1)):
        raise AppError(409, 'VERSION_FROZEN', '该版本已冻结或被作业引用，请新建版本后修改')
    if version.updated_at != expected:
        raise AppError(409, 'VERSION_CONFLICT', '其他页面已修改此版本，请重新载入后编辑')


def update_version(db, version_id, user, body):
    problem, version = version_context(db, version_id, user, lock=True)
    ensure_editable(db, problem, version, body.expected_updated_at)
    write_configuration(db, problem, version, body.version, user.id)
    problem.updated_at = utcnow()
    return version_view(db, problem, version)


def fork_version(db, problem_id, user, body):
    problem = problem_context(db, problem_id, user, lock=True)
    if problem.status != 'ACTIVE':
        raise AppError(409, 'PROBLEM_ARCHIVED', '请先恢复题目')
    versions = list(db.scalars(select(ProblemVersion).where(ProblemVersion.problem_id == problem.id)))
    draft = next((v for v in versions if v.status == 'DRAFT'), None)
    if draft is not None:
        raise AppError(409, 'DRAFT_EXISTS', '已有可编辑草稿，请先完成或编辑该草稿', {'version_id': str(draft.id)})
    source = next((v for v in versions if v.id == body.source_version_id), None)
    if source is None:
        raise AppError(404, 'NOT_FOUND', '来源版本不属于该题目')
    raw = version_view(db, problem, source)
    payload = {key: raw[key] for key in VERSION_FIELDS}
    payload['knowledge_point_ids'] = raw['knowledge_point_ids']
    payload['reference_solutions'] = [{'language': r['language'], 'content': r['content']}
                                       for r in raw['reference_solutions']]
    payload['test_suite'] = {k: v for k, v in raw['test_suite'].items() if k not in {'id', 'version_no'}} if raw['test_suite'] else None
    payload['rubric'] = {k: v for k, v in raw['rubric'].items() if k != 'id'} if raw['rubric'] else None
    parsed = VersionInput.model_validate(payload)
    version = ProblemVersion(problem_id=problem.id, version_no=max(v.version_no for v in versions) + 1,
        title=parsed.title, statement_md=parsed.statement_md, difficulty_level=parsed.difficulty_level,
        created_by=user.id)
    db.add(version)
    db.flush()
    write_configuration(db, problem, version, parsed, user.id)
    problem.updated_at = utcnow()
    return version_view(db, problem, version)


def freeze_version(db, version_id, user, body):
    problem, version = version_context(db, version_id, user, lock=True)
    ensure_editable(db, problem, version, body.expected_updated_at)
    validate_ready(db, problem, version)
    version.status = 'FROZEN'
    version.frozen_at = utcnow()
    version.updated_at = utcnow()
    problem.updated_at = utcnow()
    db.flush()
    return version_view(db, problem, version)


def validate_ready(db, problem, version, *, suite_id=None, rubric_id=None, check_node=False):
    """One completeness rule for freezing, assignment publication and reopening."""
    view = version_view(db, problem, version)
    if suite_id is not None:
        selected = db.get(TestSuite, suite_id)
        if selected is None or selected.problem_version_id != version.id or selected.status != 'FROZEN':
            raise AppError(422, 'INVALID_ASSIGNMENT_CONFIGURATION', '测试集不属于选定题目版本')
        cases = list(db.scalars(select(TestCase).where(TestCase.test_suite_id == selected.id)))
        view['test_suite'] = {'cases': [{'weight': str(c.weight)} for c in cases],
            'cpu_limit_ms': selected.cpu_limit_ms, 'total_budget_ms': selected.total_budget_ms,
            'allowed_languages': selected.allowed_languages, 'checker': selected.checker}
    if rubric_id is not None:
        selected = db.get(Rubric, rubric_id)
        if selected is None or selected.problem_version_id != version.id or selected.status != 'FROZEN':
            raise AppError(422, 'INVALID_ASSIGNMENT_CONFIGURATION', '量表不属于选定题目版本')
        view['rubric'] = {'items': [{'name': d.name, 'description': d.description} for d in
            db.scalars(select(RubricItem).where(RubricItem.rubric_id == rubric_id))]}
    missing = []
    if not view['knowledge_point_ids']:
        missing.append('至少一个课程知识点')
    elif db.scalar(select(func.count()).select_from(KnowledgePoint).where(
            KnowledgePoint.id.in_([int(i) for i in view['knowledge_point_ids']]),
            KnowledgePoint.course_id == problem.course_id, KnowledgePoint.status == 'ACTIVE')) != len(view['knowledge_point_ids']):
        missing.append('所有知识点必须属于当前课程且处于启用状态')
    if not view['reference_solutions'] or not all(r['content'].strip() for r in view['reference_solutions']):
        missing.append('完整的教师参考答案或参考代码')
    if problem.question_type == 'PROGRAMMING':
        suite = view['test_suite']
        if not suite or not suite['cases']:
            missing.append('至少一个测试用例')
        elif sum(Decimal(case['weight']) for case in suite['cases']) != Decimal(1):
            missing.append('测试用例权重之和必须等于 1')
        if not version.input_spec_md or not version.input_spec_md.strip():
            missing.append('输入说明')
        if not version.output_spec_md or not version.output_spec_md.strip():
            missing.append('输出说明')
        if suite:
            try:
                judge_config.validate_budget(suite['cpu_limit_ms'], len(suite['cases']), suite['total_budget_ms'])
            except ValueError as error:
                missing.append(str(error))
            if suite['checker'] != 'TEXT_TRIM_TRAILING' or not suite['allowed_languages'] or any(
                    lang not in {'python3', 'cpp', 'c', 'java'} for lang in suite['allowed_languages']):
                missing.append('当前支持的比较方式与编程语言')
            if check_node and (not judge_config.driver_available() or any(
                    judge_config.toolchain(lang) is None for lang in suite['allowed_languages'])):
                missing.append('当前评测节点尚不支持此题全部语言，请配置工具链或先只读发布')
    else:
        rubric = view['rubric']
        if not rubric or not rubric['items']:
            missing.append('至少一个评分维度')
        elif any(not dim['name'].strip() or not dim['description'].strip() for dim in rubric['items']):
            missing.append('各评分维度的名称与具体评分说明')
    if missing:
        raise AppError(422, 'FREEZE_VALIDATION_FAILED', '请补齐题目配置后再冻结', {'requirements': missing})


def create_knowledge(db, course_id, user, body):
    require_teacher(db, course_id, user.id)
    existing = db.scalar(select(KnowledgePoint).where(KnowledgePoint.course_id == course_id,
                                                    KnowledgePoint.name == body.name))
    if existing:
        if existing.status != 'ACTIVE':
            raise AppError(409, 'KNOWLEDGE_POINT_INACTIVE', '同名知识点已停用，请联系课程负责人')
        return {'id': str(existing.id), 'name': existing.name, 'code': existing.code}
    code = 'T_' + hashlib.sha256(body.name.encode()).hexdigest()[:30]
    point = KnowledgePoint(course_id=course_id, code=code, name=body.name)
    db.add(point)
    db.flush()
    return {'id': str(point.id), 'name': point.name, 'code': point.code}
