from copy import deepcopy
import pytest
from sqlalchemy import func, select
from app.db.models import Problem, ProblemVersion, Rubric, TestSuite as ProblemTestSuite, AssignmentItem, Course, CourseMember, User, KnowledgePoint


@pytest.fixture
def teacher(client, demo, auth):
    return auth('demo.teacher'), demo[0]['course_id']


def payload(client, teacher, kind='ALGORITHM_ANALYSIS', code='TEACHER-01'):
    headers, course = teacher
    tag = client.post(f'/api/v1/teacher/courses/{course}/knowledge-points', headers=headers, json={'name': '教师端测试知识点'})
    assert tag.status_code == 201, tag.text
    version = {'title': '递推式与边界条件', 'statement_md': '求解 $T(n)=2T(n/2)+n$。',
        'difficulty_level': 3, 'knowledge_point_ids': [tag.json()['id']],
        'reference_solutions': [{'content': '由主定理可得 Θ(n log n)，边界 T(1)=Θ(1)。'}]}
    if kind == 'PROGRAMMING':
        version.update(input_spec_md='一个整数', output_spec_md='原样输出', test_suite={
            'cases': [{'input_text': '1\n', 'expected_output': '1\n', 'weight': '1', 'is_public': False}]})
    else:
        version['rubric'] = {'items': [{'name': '正确性', 'description': '给出完整推理和边界讨论', 'max_score': '100.00'}]}
    return {'code': code, 'question_type': kind, 'version': version}


@pytest.mark.parametrize('kind', ['PROGRAMMING', 'ALGORITHM_ANALYSIS', 'PROOF', 'OPEN_QUESTION'])
def test_all_types_create_edit_freeze_fork_keep_original(client, teacher, db, kind):
    headers, course = teacher
    body = payload(client, teacher, kind)
    response = client.post(f'/api/v1/teacher/courses/{course}/problems', headers=headers, json=body)
    assert response.status_code == 201, response.text
    first = response.json()
    assert first['status'] == 'DRAFT' and isinstance(first['id'], str)
    body['version']['title'] = '修改后的题目'
    changed = client.put(f"/api/v1/teacher/problem-versions/{first['id']}", headers=headers,
        json={'expected_updated_at': first['updated_at'], 'version': body['version']})
    assert changed.status_code == 200, changed.text
    edited = changed.json()
    stale = client.put(f"/api/v1/teacher/problem-versions/{first['id']}", headers=headers,
        json={'expected_updated_at': first['updated_at'], 'version': body['version']})
    assert stale.status_code == 409 and stale.json()['code'] == 'VERSION_CONFLICT'
    model = ProblemTestSuite if kind == 'PROGRAMMING' else Rubric
    assert db.scalar(select(func.count()).select_from(model).where(model.problem_version_id == int(first['id']))) == 2
    frozen = client.post(f"/api/v1/teacher/problem-versions/{first['id']}/freeze", headers=headers, json={'expected_updated_at': edited['updated_at']})
    assert frozen.status_code == 200, frozen.text
    assert frozen.json()['status'] == 'FROZEN'
    assert client.put(f"/api/v1/teacher/problem-versions/{first['id']}", headers=headers,
        json={'expected_updated_at': frozen.json()['updated_at'], 'version': body['version']}).status_code == 409
    forked = client.post(f"/api/v1/teacher/problems/{first['problem_id']}/versions", headers=headers, json={'source_version_id': first['id']})
    assert forked.status_code == 201, forked.text
    assert forked.json()['version_no'] == 2 and forked.json()['status'] == 'DRAFT'
    assert client.post(f"/api/v1/teacher/problems/{first['problem_id']}/versions", headers=headers, json={'source_version_id': first['id']}).status_code == 409
    original = client.get(f"/api/v1/teacher/problem-versions/{first['id']}", headers=headers).json()
    assert original == frozen.json()
    assert client.get(f'/api/v1/teacher/courses/{course}/problems?q=修改', headers=headers).json()['total'] == 1
    assert client.post(f"/api/v1/teacher/problems/{first['problem_id']}/archive", headers=headers).status_code == 200
    assert client.get(f'/api/v1/teacher/courses/{course}/problems', headers=headers).json()['total'] == 4
    assert client.get(f'/api/v1/teacher/courses/{course}/problems?status=ARCHIVED', headers=headers).json()['total'] == 1
    assert client.post(f"/api/v1/teacher/problems/{first['problem_id']}/restore", headers=headers).status_code == 200


def test_validation_duplicate_permissions_and_atomic_rollback(client, teacher, auth, db):
    headers, course = teacher
    body = payload(client, teacher)
    other = Course(code='OTHER', name='另一门课程', term='2026', created_by=db.scalar(select(User.id).where(User.login_name == 'demo.teacher')))
    db.add(other); db.flush()
    tag = KnowledgePoint(course_id=other.id, code='OTHER-TAG', name='其他课程知识点'); db.add(tag); db.commit()
    invalid = deepcopy(body); invalid['version']['knowledge_point_ids'] = [str(tag.id)]
    count = db.scalar(select(func.count()).select_from(Problem))
    response = client.post(f'/api/v1/teacher/courses/{course}/problems', headers=headers, json=invalid)
    assert response.status_code == 422
    assert db.scalar(select(func.count()).select_from(Problem)) == count
    assert client.post(f'/api/v1/teacher/courses/{course}/problems', headers=auth(), json=body).status_code == 403
    assert client.get(f'/api/v1/teacher/courses/{other.id}/problems', headers=headers).status_code == 404
    first = client.post(f'/api/v1/teacher/courses/{course}/problems', headers=headers, json=body).json()
    assert client.post(f'/api/v1/teacher/courses/{course}/problems', headers=headers, json=body).status_code == 409
    assert client.get(f"/api/v1/teacher/problem-versions/{first['id']}", headers=auth()).status_code == 403
    invalid = deepcopy(body); invalid['code'] = 'NUL'; invalid['version']['rubric']['items'][0]['description'] = '\x00'
    assert client.post(f'/api/v1/teacher/courses/{course}/problems', headers=headers, json=invalid).status_code == 422


def test_freeze_incomplete_rejected_and_shared_assignment_preserved(client, teacher, demo, auth, db):
    headers, course = teacher
    body = payload(client, teacher, 'PROGRAMMING'); body['version']['test_suite']['cases'][0]['weight'] = '.5'
    created = client.post(f'/api/v1/teacher/courses/{course}/problems', headers=headers, json=body).json()
    result = client.post(f"/api/v1/teacher/problem-versions/{created['id']}/freeze", headers=headers, json={'expected_updated_at': created['updated_at']})
    assert result.status_code == 422 and '权重' in str(result.json())
    item_id = demo[0]['items'][0]['id']
    before = client.get(f'/api/v1/assignment-items/{item_id}', headers=auth()).json()
    assignment_item = db.get(AssignmentItem, int(item_id))
    original_version = db.get(ProblemVersion, assignment_item.problem_version_id)
    fork = client.post(f'/api/v1/teacher/problems/{original_version.problem_id}/versions', headers=headers, json={'source_version_id': str(original_version.id)})
    assert fork.status_code == 201, fork.text
    assert client.post(f'/api/v1/teacher/problems/{original_version.problem_id}/archive', headers=headers).status_code == 200
    after = client.get(f'/api/v1/assignment-items/{item_id}', headers=auth()).json()
    assert before == after
    assert 'reference_solutions' not in after and 'test_cases' not in after
