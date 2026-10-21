"""Import verified, portable snapshots; never log roster identities."""
import hashlib
import json
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import ROOT
from app.db.base import utcnow
from app.db.models import (User, Class, StudentProfile, Course, CourseMember, Problem,
    ProblemVersion, KnowledgePoint, ProblemVersionTag, TestSuite, TestCase,
    ReferenceSolution, Rubric, RubricItem)

COURSE_CODE = 'ALGO_FULL_2026'
FILES = ('questions.programming.json', 'questions.subjective.json', 'students.anonymized.json')


def load_snapshot(directory: Path = ROOT / 'data/formatted', students_file: Path | None = None,
                  allow_private: bool = False):
    manifest = json.loads((directory / 'manifest.json').read_text(encoding='utf-8'))
    # Filenames are fixed by our contract, not supplied by an untrusted manifest.
    hashes = manifest['sha256']
    for name in FILES:
        if hashlib.sha256((directory / name).read_bytes()).hexdigest() != hashes[name]:
            raise ValueError('Snapshot checksum mismatch: ' + name)
    questions = []
    for name in FILES[:2]:
        payload = json.loads((directory / name).read_text(encoding='utf-8'))
        questions.extend(payload['questions'] if isinstance(payload, dict) else payload)
    public = json.loads((directory / FILES[2]).read_text(encoding='utf-8'))
    roster = public
    if students_file is not None:
        roster = json.loads(students_file.read_text(encoding='utf-8'))
        if roster.get('privacy') != 'anonymized':
            if not allow_private or roster.get('privacy') != 'real-local-only':
                raise ValueError('Private roster requires --allow-private.')
            if students_file.resolve().is_relative_to(ROOT.resolve()):
                raise ValueError('Private roster must remain outside the repository.')
        keys = lambda r: {(s['record_key'], s['login_name'], s['class_code']) for s in r['students']}
        if keys(roster) != keys(public) or {c['class_code'] for c in roster['classes']} != {c['class_code'] for c in public['classes']}:
            raise ValueError('Roster stable keys differ from the public snapshot.')
    return questions, roster


def proportions(values):
    values = [Decimal(str(v)) for v in values]
    if not values or any(v <= 0 for v in values):
        raise ValueError('Positive weights are required.')
    total = sum(values)
    result = [(v / total).quantize(Decimal('0.000001')) for v in values]
    result[-1] = Decimal(1) - sum(result[:-1])
    if min(result) <= 0:
        raise ValueError('Weight is below database precision.')
    return result


def fingerprint(record):
    return hashlib.sha256(json.dumps(record, ensure_ascii=False, sort_keys=True,
        separators=(',', ':')).encode('utf-8')).hexdigest()


def import_snapshot(session: Session, questions: list, roster: dict) -> dict:
    """Caller owns the transaction. Repeated identical imports create no rows."""
    counts = dict(created_students=0, created_classes=0, created_problems=0, created_versions=0)
    teacher = session.scalar(select(User).where(User.login_name == 'demo.teacher'))
    if teacher is None:
        raise ValueError('Run seed_demo before importing the full snapshot.')
    course = session.scalar(select(Course).where(Course.code == COURSE_CODE))
    if course is None:
        course = Course(code=COURSE_CODE, name='算法设计与分析（全量题库）', term='2026-2027-1', created_by=teacher.id)
        session.add(course); session.flush()
        session.add(CourseMember(course_id=course.id, user_id=teacher.id, role='TEACHER'))
    classes = {}
    for row in roster['classes']:
        cls = session.scalar(select(Class).where(Class.class_code == row['class_code']))
        if cls is None:
            cls = Class(class_code=row['class_code'], name=row['name'])
            session.add(cls); session.flush(); counts['created_classes'] += 1
        elif cls.name != row['name']:
            raise ValueError('Roster identity mode conflicts with existing classes; use a separate database.')
        classes[row['class_code']] = cls
    for row in roster['students']:
        user = session.scalar(select(User).where(User.login_name == row['login_name']))
        if user is None:
            user = User(login_name=row['login_name'], student_no=row['student_no'],
                        full_name=row['full_name'], status='PENDING', password_hash=None)
            session.add(user); session.flush(); counts['created_students'] += 1
        elif user.student_no != row['student_no'] or user.full_name != row['full_name']:
            raise ValueError('Roster identity mode conflicts with existing users; use a separate database.')
        profile = session.scalar(select(StudentProfile).where(StudentProfile.user_id == user.id))
        if profile is None:
            session.add(StudentProfile(user_id=user.id, class_id=classes[row['class_code']].id))
        elif profile.class_id != classes[row['class_code']].id:
            raise ValueError('Existing student class conflicts with snapshot.')
        member = session.scalar(select(CourseMember).where(CourseMember.course_id == course.id, CourseMember.user_id == user.id))
        if member is None:
            session.add(CourseMember(course_id=course.id, user_id=user.id, role='STUDENT'))
        elif member.role != 'STUDENT':
            raise ValueError('Existing course membership conflicts with snapshot.')
    now = utcnow()
    tags = {t.name: t for t in session.scalars(select(KnowledgePoint).where(KnowledgePoint.course_id == course.id))}
    for row in questions:
        problem = session.scalar(select(Problem).where(Problem.course_id == course.id, Problem.code == row['code']))
        if problem is None:
            problem = Problem(course_id=course.id, code=row['code'], question_type=row['type'], created_by=teacher.id)
            session.add(problem); session.flush(); counts['created_problems'] += 1
        elif problem.question_type != row['type']:
            raise ValueError('Question type changed; use a new problem code.')
        versions = list(session.scalars(select(ProblemVersion).where(ProblemVersion.problem_id == problem.id)))
        digest = fingerprint(row)
        latest = max(versions, key=lambda v: v.version_no, default=None)
        if latest is not None and _source_hash(latest.source_reference) == digest:
            continue
        source = {k: row[k] for k in ('source', 'source_file', 'source_anchor', 'source_sha256',
                  'references', 'metadata', 'verification') if k in row}
        source.update(record_sha256=digest, importer='full-data-v1')
        if row['type'] == 'PROGRAMMING':
            source['resource_policy'] = 'Project default: 1000ms/262144KiB/python3; not source-verified; mock worker only.'
        examples = row.get('examples', [])
        examples_md = examples if isinstance(examples, str) else '\n\n'.join(
            f"输入\n```text\n{e['input']}\n```\n输出\n```text\n{e['output']}\n```" for e in examples)
        version = ProblemVersion(problem_id=problem.id, version_no=max((v.version_no for v in versions), default=0)+1,
            title=row['title'], statement_md=row['statement'], answer_requirements_md=row.get('requirements'),
            input_spec_md=row.get('input'), output_spec_md=row.get('output'), data_constraints_md=row.get('constraints'),
            public_examples_md=examples_md, difficulty_level=row['difficulty'], source_reference=json.dumps(source, ensure_ascii=False),
            created_by=teacher.id, status='FROZEN', frozen_at=now)
        session.add(version); session.flush(); counts['created_versions'] += 1
        tag_names = list(dict.fromkeys(row['tags']))
        for name, weight in zip(tag_names, proportions([1]*len(tag_names))):
            if name not in tags:
                tag = KnowledgePoint(course_id=course.id, code='FULL_'+hashlib.sha256(name.encode()).hexdigest()[:20], name=name)
                session.add(tag); session.flush(); tags[name] = tag
            session.add(ProblemVersionTag(problem_version_id=version.id, knowledge_point_id=tags[name].id, mastery_weight=weight))
        if row.get('reference_answer'):
            session.add(ReferenceSolution(problem_version_id=version.id, language=None, content=row['reference_answer'], created_by=teacher.id))
        languages = {'C':'c', 'C++':'cpp', 'Python':'python3'}
        for reference in row['reference_solutions']:
            session.add(ReferenceSolution(problem_version_id=version.id, language=languages[reference['language']],
                                         content=reference['content'], created_by=teacher.id))
        if row['type'] == 'PROGRAMMING':
            suite = TestSuite(problem_version_id=version.id, version_no=1, cpu_limit_ms=1000,
                memory_limit_kib=262144, allowed_languages=['python3'], frozen_at=now)
            session.add(suite); session.flush()
            for order, (case, weight) in enumerate(zip(row['tests'], proportions([t['weight'] for t in row['tests']])), 1):
                session.add(TestCase(test_suite_id=suite.id, sort_order=order, input_text=case['input'],
                                    expected_output=case['output'], weight=weight, is_public=case['public']))
        else:
            rubric = Rubric(problem_version_id=version.id, version_no=1, name='源题评分量表', frozen_at=now)
            session.add(rubric); session.flush()
            for order, item in enumerate(row['rubric'], 1):
                session.add(RubricItem(rubric_id=rubric.id, name=item['name'], description=item['description'],
                                      max_score=Decimal(str(item['max_score'])), sort_order=order))
    session.flush()
    return dict(status='ready', course_code=COURSE_CODE, course_id=str(course.id), privacy=roster['privacy'],
                questions=len(questions), students=len(roster['students']), classes=len(roster['classes']), **counts)


def _source_hash(value):
    try:
        return json.loads(value or '{}').get('record_sha256')
    except (ValueError, AttributeError):
        return None
