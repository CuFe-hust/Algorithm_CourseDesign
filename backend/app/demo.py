from datetime import timedelta
from decimal import Decimal
import json
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.config import ROOT
from app.common.security import hash_password
from app.db.base import utcnow
from app.db.models import (User, Class, StudentProfile, Course, CourseMember, Problem, ProblemVersion,
    KnowledgePoint, ProblemVersionTag, TestSuite, TestCase, ReferenceSolution, Rubric, RubricItem,
    Assignment, AssignmentItem, AssignmentParticipant)


def demo_summary(session: Session) -> dict:
    course = session.scalar(select(Course).where(Course.code == 'DEMO_ALGO'))
    assignments = list(session.scalars(select(Assignment).where(Assignment.course_id == course.id).order_by(Assignment.id)))
    items = session.execute(select(AssignmentItem, Problem).join(ProblemVersion, AssignmentItem.problem_version_id == ProblemVersion.id)
                            .join(Problem, ProblemVersion.problem_id == Problem.id)
                            .join(Assignment, AssignmentItem.assignment_id == Assignment.id)
                            .where(Assignment.course_id == course.id).order_by(AssignmentItem.id)).all()
    return {'course_id': str(course.id), 'teacher_login': 'demo.teacher',
            'student_logins': [f'demo.student{i:02}' for i in range(1, 7)],
            'assignments': [{'id': str(a.id), 'title': a.title} for a in assignments],
            'items': [{'id': str(i.id), 'assignment_id': str(i.assignment_id), 'code': p.code, 'type': p.question_type} for i, p in items]}


def seed_demo(session: Session, password: str, deadline_days: int = 7) -> dict:
    if len(password) < 12 or not 1 <= deadline_days <= 365:
        raise ValueError('Demo password must have at least 12 characters; deadline_days must be 1..365.')
    if session.scalar(select(Course.id).where(Course.code == 'DEMO_ALGO')):
        return demo_summary(session)
    if session.scalar(select(User.id).where(User.login_name.like('demo.%'))):
        raise ValueError('Demo account names already exist without a demo course; refusing to overwrite.')
    now = utcnow()
    # One hash is shared only by these synthetic demo accounts. Never use this seed for real users.
    hashed = hash_password(password)
    teacher = User(login_name='demo.teacher', full_name='演示教师', password_hash=hashed, status='ACTIVE')
    students = [User(login_name=f'demo.student{i:02}', student_no=f'DEMO2026{i:03}',
                     full_name='演示同学' if i in (1, 2) else f'演示同学{i}', password_hash=hashed, status='ACTIVE') for i in range(1, 7)]
    classes = [Class(class_code=f'DEMO_CLASS_{i}', name=f'演示班{i}', status='ACTIVE') for i in (1, 2)]
    session.add_all([teacher, *students, *classes]); session.flush()
    course = Course(code='DEMO_ALGO', name='算法设计与分析（合成演示）', term='2026-2027-1', created_by=teacher.id)
    session.add(course); session.flush()
    session.add(CourseMember(course_id=course.id, user_id=teacher.id, role='TEACHER'))
    for n, student in enumerate(students):
        session.add(StudentProfile(user_id=student.id, class_id=classes[n // 3].id))
        session.add(CourseMember(course_id=course.id, user_id=student.id, role='STUDENT'))
    source = json.loads((ROOT / 'data/demo/problems.json').read_text(encoding='utf-8'))
    entries = []
    tags = {}
    for data in source:
        problem = Problem(course_id=course.id, code=data['code'], question_type=data['type'], created_by=teacher.id)
        session.add(problem); session.flush()
        version = ProblemVersion(problem_id=problem.id, version_no=1, title=data['title'], statement_md=data['statement'],
            answer_requirements_md=data.get('requirements'), input_spec_md=data.get('input'), output_spec_md=data.get('output'),
            data_constraints_md=data.get('constraints'), public_examples_md=data.get('examples'), difficulty_level=data['difficulty'],
            source_reference=data['source'], created_by=teacher.id, status='FROZEN', frozen_at=now)
        session.add(version); session.flush()
        weights = [Decimal('1') / len(data['tags']) for _ in data['tags']]
        weights = [w.quantize(Decimal('0.000001')) for w in weights]
        weights[-1] = Decimal('1') - sum(weights[:-1])
        for tag, weight in zip(data['tags'], weights):
            if tag not in tags:
                tags[tag] = KnowledgePoint(course_id=course.id, code=f'DEMO_KP_{len(tags)+1}', name=tag)
                session.add(tags[tag]); session.flush()
            session.add(ProblemVersionTag(problem_version_id=version.id, knowledge_point_id=tags[tag].id, mastery_weight=weight))
        session.add(ReferenceSolution(problem_version_id=version.id, content=data['reference'],
                    language='python3' if data['type'] == 'PROGRAMMING' else None, created_by=teacher.id))
        suite = rubric = None
        if data['type'] == 'PROGRAMMING':
            suite = TestSuite(problem_version_id=version.id, version_no=1, cpu_limit_ms=1000,
                              memory_limit_kib=262144, allowed_languages=['python3'], frozen_at=now)
            session.add(suite); session.flush()
            for n, case in enumerate(data['tests'], 1):
                session.add(TestCase(test_suite_id=suite.id, sort_order=n, input_text=case['input'],
                                    expected_output=case['output'], weight=Decimal('0.2'), is_public=case['public']))
        else:
            rubric = Rubric(problem_version_id=version.id, version_no=1, name='演示评分量表', frozen_at=now)
            session.add(rubric); session.flush()
            for n, (name, score) in enumerate(data['rubric'], 1):
                session.add(RubricItem(rubric_id=rubric.id, name=name, description='依据该维度的正确性与完整性给分', max_score=score, sort_order=n))
        entries.append((version, suite, rubric))
    for title, selected in [('演示作业：编程题', entries[:1]), ('演示作业：四类混合题', entries)]:
        assignment = Assignment(course_id=course.id, title=title, description_md='合成演示作业，编程结果仅为模拟联调。',
            created_by=teacher.id, submission_deadline=now+timedelta(days=deadline_days),
            review_deadline=now+timedelta(days=deadline_days+2) if len(selected)>1 else None,
            submission_status='OPEN', published_by=teacher.id, published_at=now-timedelta(minutes=1))
        session.add(assignment); session.flush()
        for n, (version, suite, rubric) in enumerate(selected, 1):
            session.add(AssignmentItem(assignment_id=assignment.id, problem_version_id=version.id, sort_order=n,
                max_score=100, required_reviewers=2 if rubric else 0,
                test_suite_id=suite.id if suite else None, rubric_id=rubric.id if rubric else None))
        for n, student in enumerate(students):
            cls = classes[n // 3]
            session.add(AssignmentParticipant(assignment_id=assignment.id, student_id=student.id,
                        class_id_at_publish=cls.id, class_name_at_publish=cls.name))
    session.commit()
    return demo_summary(session)
