import time

import pytest
from app.judge import config, local
from test_teacher_authoring import payload, teacher


def test_budget_snapshot_freeze_node_bound_and_student_projection(client, teacher, auth, demo, monkeypatch):
    headers, course = teacher
    body = payload(client, teacher, 'PROGRAMMING')
    body['version']['test_suite']['total_budget_ms'] = 1000
    a = client.post(f'/api/v1/teacher/courses/{course}/problems', headers=headers, json=body).json()
    frozen = client.post(f"/api/v1/teacher/problem-versions/{a['id']}/freeze", headers=headers, json={'expected_updated_at':a['updated_at']})
    assert frozen.status_code == 422 and '总预算' in str(frozen.json())
    body['version']['test_suite']['total_budget_ms'] = 40000
    a = client.put(f"/api/v1/teacher/problem-versions/{a['id']}", headers=headers,
        json={'expected_updated_at':a['updated_at'],'version':body['version']}).json()
    monkeypatch.setenv('JUDGE_MAX_TOTAL_BUDGET_MS', '39000')
    assert client.post(f"/api/v1/teacher/problem-versions/{a['id']}/freeze", headers=headers, json={'expected_updated_at':a['updated_at']}).status_code == 422
    monkeypatch.setenv('JUDGE_MAX_TOTAL_BUDGET_MS', '300000')
    assert client.post(f"/api/v1/teacher/problem-versions/{a['id']}/freeze", headers=headers, json={'expected_updated_at':a['updated_at']}).status_code == 200
    item = next(i for i in demo[0]['items'] if i['type']=='PROGRAMMING')
    public = client.get(f"/api/v1/assignment-items/{item['id']}", headers=auth()).json()
    assert public['execution_budget']['budget_source'] == 'LEGACY_DERIVED'
    assert public['execution_budget']['total_budget_ms'] == config.minimum_total_budget_ms(1000,5)
    assert 'test_cases' not in public


def test_aggregate_budget_really_stops_multiple_individually_valid_runs(judge_work_root, monkeypatch):
    # Lower only the admission minimum for this small real-process timing test.
    monkeypatch.setattr(config, 'minimum_total_budget_ms', lambda *args: 1000)
    start = time.monotonic()
    result = local.execute('import time; time.sleep(.7); print(1)', 'python3',
        [local.CaseInput(1,'','1\n'),local.CaseInput(2,'','1\n'),local.CaseInput(3,'','1\n')], 1000, total_budget_ms=1000)
    assert result.verdict == 'TIME_LIMIT_EXCEEDED'
    assert result.passed == 1 and result.executed < result.total
    assert time.monotonic()-start < 4


def test_budget_accounts_for_compile_cases_and_overheads(monkeypatch):
    assert config.minimum_total_budget_ms(1000,20) == 100000
    assert config.suite_budget(1000,20,None)['budget_source'] == 'LEGACY_DERIVED'
    assert config.suite_budget(1000,20,120000)['budget_source'] == 'TEACHER'
    with pytest.raises(ValueError): config.validate_budget(30000,200,300000)
    monkeypatch.setenv('JUDGE_MAX_TOTAL_BUDGET_MS','60000')
    with pytest.raises(ValueError): config.validate_budget(1000,20,120000)
