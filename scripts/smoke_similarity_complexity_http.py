"""HTTP smoke for code similarity and complexity analysis on localhost.

Run from the repository root with the API running in LOCAL mode and a worker
available:

    .venv/bin/python scripts/smoke_similarity_complexity_http.py

The script logs in as the demo teacher and students, submits a small set of
synthetic solutions to the demo programming item, runs a similarity batch, reads
the evidence, then requests and reads a complexity report for a really accepted
submission. It asserts permissions and the JSON shape the frontend consumes.

Only synthetic demo accounts are used; credentials are read from .env and never
printed or written. The script accepts only a localhost HTTP base URL.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
import uuid
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import ProxyHandler, Request, build_opener

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
BASE = sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:8000'
parsed = urlparse(BASE)
if parsed.scheme != 'http' or parsed.hostname not in {'127.0.0.1', 'localhost'} or parsed.path not in ('', '/'):
    raise SystemExit('This synthetic smoke accepts only a localhost HTTP base URL.')
opener = build_opener(ProxyHandler({}))
checks = 0

# Three near-identical solutions (rename / comment only), one structurally
# different but still accepted, one unrelated, one too short to compare.
CODES = {
    'demo.student01': '''n = int(input())
a = [tuple(map(int, input().split())) for _ in range(n)]
last, ans = -1, 0
for s, t in sorted(a, key=lambda p: (p[1], p[0])):
    if s >= last:
        last, ans = t, ans + 1
print(ans)
''',
    'demo.student02': '''count = int(input())
items = [tuple(map(int, input().split())) for _ in range(count)]
end_time = -1
total = 0
for start, finish in sorted(items, key=lambda pair: (pair[1], pair[0])):
    if start >= end_time:
        end_time, total = finish, total + 1
print(total)
''',
    # Third near-identical solution: only comments, spacing and variable names
    # differ, so the three together must form one cluster.
    'demo.student03': '''# 贪心：按结束时间排序后依次接纳
n = int(input())
intervals = [tuple(map(int, input().split())) for _ in range(n)]
finish_of_last = -1
picked = 0
for begin, end in sorted(intervals, key=lambda item: (item[1], item[0])):
    if begin >= finish_of_last:
        finish_of_last, picked = end, picked + 1
print(picked)
''',
    'demo.student04': '''import sys
data = sys.stdin.read().split()
n = int(data[0])
pairs = [(int(data[1 + 2 * i]), int(data[2 + 2 * i])) for i in range(n)]
pairs.sort(key=lambda item: item[1])
answer = 0
boundary = -1
for start, end in pairs:
    if start >= boundary:
        answer += 1
        boundary = end
print(answer)
''',
    'demo.student05': '''n = int(input())
best = 0
for _ in range(n):
    s, t = map(int, input().split())
    best = max(best, t - s)
print(best)
''',
    'demo.student06': 'print(0)\n',
}


def api(path, *, token=None, method='GET', body=None, expected=200):
    global checks
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    payload = json.dumps(body).encode() if body is not None else None
    request = Request(BASE + '/api/v1' + path, data=payload, headers=headers, method=method)
    try:
        with opener.open(request, timeout=30) as response:
            status, result = response.status, json.load(response)
    except HTTPError as error:
        status, result = error.code, json.load(error)
    if status != expected:
        raise AssertionError(f'{method} {path}: expected {expected}, got {status}; '
                             f'code={result.get("code")} message={result.get("message")}')
    checks += 1
    return result


def run_worker(module: str, *args: str) -> str:
    """Run one worker pass so the smoke does not depend on a background process."""
    completed = subprocess.run([sys.executable, '-m', module, *args], cwd=str(ROOT / 'backend'),
                               capture_output=True, text=True, timeout=300,
                               env={**__import__('os').environ, 'JUDGE_EXECUTION_MODE': 'LOCAL'})
    if completed.returncode != 0:
        raise AssertionError(f'{module} failed: {completed.stderr[-600:]}')
    return completed.stdout


def main() -> int:
    password = dotenv_values(ROOT / '.env')['DEMO_PASSWORD']
    teacher = api('/auth/login', method='POST',
                  body={'login_name': 'demo.teacher', 'password': password})['access_token']
    courses = api('/courses', token=teacher)['items']
    course = next(row for row in courses if row['role'] == 'TEACHER' and '合成演示' in row['name'])['id']

    capabilities = api(f'/teacher/courses/{course}/judge-capabilities', token=teacher)
    if capabilities['execution_mode'] != 'LOCAL':
        raise SystemExit('Start the API with JUDGE_EXECUTION_MODE=LOCAL for this smoke.')

    scope = api(f'/analysis/courses/{course}/code-similarity/scope', token=teacher)
    assignment = next((row for row in scope['items'] if row['items']), None)
    if assignment is None:
        raise SystemExit('Seed the demo course first (python -m scripts.seed_demo).')
    item_id = assignment['items'][0]['item_id']
    assignment_id = assignment['id']

    # 1. Each demo student submits their synthetic solution and waits for a real verdict.
    submissions: dict[str, str] = {}
    for login, source in CODES.items():
        token = api('/auth/login', method='POST',
                    body={'login_name': login, 'password': password})['access_token']
        receipt = api(f'/assignment-items/{item_id}/submissions', token=token, method='POST', expected=202,
                      body={'content': source, 'language': 'python3',
                            'client_request_id': f'smoke-{uuid.uuid4().hex}'})
        submissions[login] = receipt['submission_id']
    # One scheduler pass claims at most `concurrency` jobs, so keep draining
    # until every submission has a stored result.
    for _ in range(len(submissions)):
        run_worker('scripts.run_judge', '--once', '--mode', 'LOCAL')
        if all(api(f'/submissions/{sid}', token=teacher)['result'] for sid in submissions.values()):
            break
    for login, submission_id in submissions.items():
        detail = api(f'/submissions/{submission_id}', token=teacher)
        result = detail['result']
        if result is None:
            raise AssertionError(f'{login} still has no verdict after draining the queue')
        print(f'  {login}: v{detail["version_no"]} {result["verdict"]}'
              f' ({result["passed_cases"]}/{result["total_cases"]})')

    # 2. Similarity batch over the assignment, then read the teacher evidence.
    batch = api(f'/analysis/courses/{course}/code-similarity/batches', token=teacher, method='POST',
                expected=201, body={'request_id': f'smoke-sim-{uuid.uuid4().hex}',
                                    'assignment_id': assignment_id, 'threshold': '0.5'})
    run_worker('scripts.run_analysis', '--limit', '20')
    evidence = api(f'/analysis/batches/{batch["id"]}/similarity', token=teacher)
    compared = evidence['items'][0]
    assert compared['status'] == 'SUCCEEDED', compared['status']
    assert compared['pairs'], 'at least one copied pair must be reported'
    pair = compared['pairs'][0]
    assert pair['left']['student_no'] and pair['right']['student_no']
    assert pair['spans'] and pair['spans'][0]['left_start_line'] >= 1
    assert any(row['reason'] == 'INSUFFICIENT_TOKENS' for row in compared['insufficient']), \
        'the too-short submission must be explained, not silently dropped'
    print(f'  similarity: {len(compared["pairs"])} pairs, '
          f'{len(compared["clusters"])} clusters, top={pair["similarity"]}')

    student = api('/auth/login', method='POST',
                  body={'login_name': 'demo.student01', 'password': password})['access_token']
    assert api(f'/analysis/batches/{batch["id"]}/similarity', token=student,
               expected=403)['code'] == 'TEACHER_REQUIRED'

    # 3. Complexity report for a really accepted submission.
    accepted = [sid for sid in submissions.values()
                if (api(f'/submissions/{sid}', token=teacher)['result'] or {}).get('verdict') == 'ACCEPTED']
    assert accepted, 'the smoke needs at least one accepted submission'
    target = accepted[0]
    api(f'/analysis/submissions/{target}/complexity', token=student, method='POST', expected=202,
        body={'request_id': f'smoke-cx-{uuid.uuid4().hex}'})
    run_worker('scripts.run_complexity', '--limit', '5')
    report = api(f'/analysis/submissions/{target}/complexity', token=student)
    assert report['status'] in ('SUCCEEDED', 'NOT_MEASURABLE'), report['status']
    body = report['report']
    assert body['limitations']
    if report['status'] == 'SUCCEEDED':
        assert body['time']['class'] and body['space']['class']
        assert body['time']['source'] == 'TRACE'
        trace = body['trace']
        assert trace['points'], 'a measured report must keep its per-rung counts'
        assert trace['evidence'] is not None
        assert body['trace_meta']['work_unit']
        print(f'  complexity: {report["status"]} time={body["time"]["class"]} '
              f'space={body["space"]["class"]} method={body["time"]["method"]} '
              f'rungs={len(trace["points"])}')
    else:
        assert body['error'], 'a NOT_MEASURABLE report must state why'
        print(f'  complexity: {report["status"]} reason={body["error"]}')

    # 4. A submission that never passed is refused, with a stated reason.
    rejected = [sid for sid in submissions.values()
                if (api(f'/submissions/{sid}', token=teacher)['result'] or {}).get('verdict') != 'ACCEPTED']
    if rejected:
        refused = api(f'/analysis/submissions/{rejected[0]}/complexity', token=teacher,
                      method='POST', expected=409,
                      body={'request_id': f'smoke-cx-bad-{uuid.uuid4().hex}'})
        assert refused['code'] == 'SUBMISSION_NOT_ACCEPTED'
        print(f'  unaccepted: refused with {refused["code"]}')

    overview = api(f'/analysis/courses/{course}/complexity', token=teacher)
    assert any(row['submission_id'] == target for row in overview['items'])
    assert api(f'/analysis/courses/{course}/complexity', token=student,
               expected=403)['code'] == 'TEACHER_REQUIRED'

    # 5. Reports are immutable evidence: asking twice returns the same single report.
    again = api(f'/analysis/submissions/{target}/complexity', token=student, method='POST',
                expected=202, body={'request_id': f'smoke-cx-{uuid.uuid4().hex}'})
    assert again['submission_id'] == target
    second = api(f'/analysis/submissions/{target}/complexity', token=student)
    assert second['report']['finished_at'] == body['finished_at'], 'a re-request must not rerun the analysis'

    print(json.dumps({'checks': checks, 'similarity_pairs': len(compared['pairs']),
                      'complexity_status': report['status']}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
