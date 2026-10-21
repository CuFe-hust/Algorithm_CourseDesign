from copy import deepcopy
from decimal import Decimal
import pytest
from sqlalchemy import select, func
from app.db.models import (Problem, ProblemVersion, User, TestCase as CaseRow, ReferenceSolution,
                           TestSuite as SuiteRow, Rubric, RubricItem, Assignment, CourseMember)
from app.full_data_import import load_snapshot, import_snapshot, COURSE_CODE


def test_full_public_snapshot_roundtrip_and_repeat(db, demo):
    questions, roster = load_snapshot()
    result = import_snapshot(db, questions, roster)
    db.commit()
    cid = int(result['course_id'])
    versions = select(ProblemVersion.id).join(Problem).where(Problem.course_id == cid)
    assert result['created_versions'] == 120
    assert result['created_students'] == 217 and result['created_classes'] == 8
    assert db.scalar(select(func.count()).select_from(CaseRow).join(SuiteRow).where(SuiteRow.problem_version_id.in_(versions))) == 350
    assert db.scalar(select(func.count()).select_from(ReferenceSolution).where(ReferenceSolution.problem_version_id.in_(versions))) == 275
    assert db.scalar(select(func.count()).select_from(Assignment).where(Assignment.course_id == cid)) == 0
    assert db.scalar(select(func.count()).select_from(CourseMember).where(CourseMember.course_id == cid, CourseMember.role == 'STUDENT')) == 217
    for total in db.scalars(select(func.sum(CaseRow.weight)).join(SuiteRow).where(SuiteRow.problem_version_id.in_(versions)).group_by(SuiteRow.id)):
        assert total == Decimal(1)
    for total in db.scalars(select(func.sum(RubricItem.max_score)).join(Rubric).where(Rubric.problem_version_id.in_(versions)).group_by(Rubric.id)):
        assert total == Decimal(100)
    student = db.scalar(select(User).where(User.login_name == roster['students'][0]['login_name']))
    assert student.status == 'PENDING' and student.password_hash is None
    repeated = import_snapshot(db, questions, roster)
    assert all(repeated[k] == 0 for k in ('created_students', 'created_classes', 'created_problems', 'created_versions'))
    changed = deepcopy(questions[0]); changed['statement'] += '\n修订测试'
    assert import_snapshot(db, [changed], roster)['created_versions'] == 1
    assert db.scalar(select(func.count()).select_from(ProblemVersion).where(ProblemVersion.id.in_(versions))) == 121
    # Reverting source content also creates a new latest frozen version.
    assert import_snapshot(db, [questions[0]], roster)['created_versions'] == 1
    latest = db.scalar(select(ProblemVersion).join(Problem).where(
        Problem.course_id == cid, Problem.code == questions[0]['code']).order_by(ProblemVersion.version_no.desc()))
    assert latest.version_no == 3 and latest.statement_md == questions[0]['statement']
    assert import_snapshot(db, [questions[0]], roster)['created_versions'] == 0
    db.rollback()
    # Different privacy modes must never silently overwrite an existing identity.
    conflicting = deepcopy(roster); conflicting['students'][0]['full_name'] = '另一个虚构身份'
    with pytest.raises(ValueError, match='identity mode'):
        import_snapshot(db, questions, conflicting)
    db.rollback()


def test_snapshot_hash_tampering_is_rejected(tmp_path):
    from app.core.config import ROOT
    import shutil
    for path in (ROOT / 'data/formatted').glob('*.json'):
        shutil.copyfile(path, tmp_path / path.name)
    with (tmp_path / 'questions.programming.json').open('ab') as file:
        file.write(b' ')
    with pytest.raises(ValueError, match='checksum'):
        load_snapshot(tmp_path)


def test_private_roster_requires_opt_in(tmp_path):
    import json
    _, roster = load_snapshot()
    roster['privacy'] = 'real-local-only'  # synthetic content only
    path = tmp_path / 'private.json'; path.write_text(json.dumps(roster), encoding='utf-8')
    with pytest.raises(ValueError, match='allow-private'):
        load_snapshot(students_file=path)
    assert load_snapshot(students_file=path, allow_private=True)[1]['privacy'] == 'real-local-only'
