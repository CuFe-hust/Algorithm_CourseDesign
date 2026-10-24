"""End-to-end HTTP smoke test for the student answer/judge chain.

It starts a real uvicorn server (or uses ``--base-url``), logs in as a synthetic
student, submits a LOCAL solution, runs one scheduler batch through the operator
CLI and verifies the summary, progress, history and status endpoints.

Safety: it only wipes and reseeds data when ``--reseed`` is given AND the target
database name ends with ``_test``. Never point it at the project database.

Example:
    DB_NAME=algorithm_review_test ../.venv/bin/python -m scripts.smoke_student_flow --reseed
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import socket
import subprocess
import sys
import time
import uuid

import httpx

OPERATOR_ENV = {
    'JUDGE_EXECUTION_MODE': 'LOCAL',
    'JUDGE_WORK_ROOT': '/tmp/algoclass-smoke-judge',
    'JUDGE_LOCK_ROOT': '/tmp/algoclass-smoke-judge/locks',
}

SOLUTION = (
    'import sys\n'
    'data = sys.stdin.read().split()\n'
    'n = int(data[0])\n'
    'pairs = sorted((int(data[2 + 2 * i]), int(data[1 + 2 * i])) for i in range(n))\n'
    'last = -1\n'
    'count = 0\n'
    'for end, start in pairs:\n'
    '    if start >= last:\n'
    '        count += 1\n'
    '        last = end\n'
    'print(count)\n'
)


class Report:
    def __init__(self):
        self.rows: list[tuple[str, bool, str]] = []

    def check(self, name: str, condition, detail: str = ''):
        self.rows.append((name, bool(condition), detail))
        if not condition:
            raise SystemExit(f'FAILED {name}: {detail}')

    def summary(self) -> int:
        for name, ok, _ in self.rows:
            print(('PASS ' if ok else 'FAIL ') + name)
        passed = sum(1 for _, ok, _ in self.rows if ok)
        print(f'{passed}/{len(self.rows)} checks passed')
        return 0 if passed == len(self.rows) else 1


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def seed(password: str) -> dict:
    from sqlalchemy import delete
    from sqlalchemy.orm import Session
    from app.db.base import Base
    from app.db import models  # noqa: F401 - registers the metadata
    from app.db.session import make_engine
    from app.demo import seed_demo

    engine = make_engine()
    try:
        with engine.begin() as connection:
            for table in reversed(Base.metadata.sorted_tables):
                connection.execute(delete(table))
        with Session(engine, expire_on_commit=False) as session:
            return seed_demo(session, password)
    finally:
        engine.dispose()


def wait_for(client: httpx.Client, timeout: float = 30.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if client.get('/api/v1/health').status_code == 200:
                return True
        except httpx.HTTPError:
            time.sleep(0.2)
    return False


def run_checks(client: httpx.Client, report: Report, password: str) -> None:
    report.check('health', client.get('/api/v1/health').status_code == 200)
    report.check('unauthorised courses', client.get('/api/v1/courses').status_code == 401)

    login = client.post('/api/v1/auth/login', json={'login_name': 'demo.student01', 'password': password})
    report.check('login', login.status_code == 200, login.text[:200])
    body = login.json()
    headers = {'Authorization': 'Bearer ' + body['access_token']}
    report.check('login fields', body['must_change_password'] is False
                 and body['absolute_expires_at'] > body['expires_at'])

    info = client.get('/api/v1/auth/session', headers=headers)
    report.check('session', info.status_code == 200 and info.json()['expires_at'] == body['expires_at'])
    report.check('renew', client.post('/api/v1/auth/renew', headers=headers).status_code == 200)

    courses = client.get('/api/v1/courses', headers=headers).json()['items']
    student_courses = [course for course in courses if course['role'] == 'STUDENT']
    report.check('student courses', len(student_courses) == 1, str(courses))
    course_id = student_courses[0]['id']
    assignments = client.get(f'/api/v1/courses/{course_id}/assignments', headers=headers).json()['items']
    report.check('assignments', bool(assignments))
    assignment = assignments[0]
    item_id = assignment['items'][0]['id']

    detail = client.get(f"/api/v1/assignments/{assignment['id']}", headers=headers).json()
    report.check('assignment detail', detail['submission_open'] is True and bool(detail['server_time']))
    item = client.get(f'/api/v1/assignment-items/{item_id}', headers=headers).json()
    report.check('public cases', item['public_test_cases'][0]['case_no'] == 1)
    report.check('hidden data absent', 'test_cases' not in item and 'expected_output' not in item)

    receipt = client.post(f'/api/v1/assignment-items/{item_id}/submissions', headers=headers,
                          json={'content': SOLUTION, 'language': 'python3',
                                'client_request_id': uuid.uuid4().hex})
    report.check('submit accepted', receipt.status_code == 202, receipt.text[:200])
    receipt = receipt.json()
    report.check('receipt queued', receipt['job_status'] == 'PENDING')

    too_large = client.post('/api/v1/auth/login', json={'login_name': 'demo.student01', 'password': 'x' * 9000})
    report.check('body limit', too_large.status_code == 413, str(too_large.status_code))

    progress = client.get(f'/api/v1/courses/{course_id}/my-progress', headers=headers,
                          params={'assignment_id': assignment['id']}).json()
    report.check('progress pending', progress['summary']['pending_job_count'] >= 1)
    discovery = client.get('/api/v1/me/judge-jobs', headers=headers,
                           params={'filter': 'DISCOVERY', 'limit': 100}).json()
    report.check('discovery', discovery['has_more'] is False and len(discovery['items']) == 1)

    run = subprocess.run([sys.executable, '-m', 'scripts.run_judge', '--once', '--mode', 'LOCAL'],
                         env={**os.environ, **OPERATOR_ENV}, capture_output=True, text=True, timeout=180)
    report.check('judge cli', run.returncode == 0 and '"started": 1' in run.stdout,
                 (run.stdout + run.stderr)[-400:])

    detail = client.get(f"/api/v1/submissions/{receipt['submission_id']}", headers=headers).json()
    result = detail.get('result') or {}
    report.check('verdict', result.get('verdict') == 'ACCEPTED', json.dumps(result, ensure_ascii=False)[:300])
    report.check('real execution', result.get('is_mock') is False and result.get('execution_mode') == 'LOCAL')
    report.check('no fake resources', result.get('cpu_time_ms') is None
                 and result.get('measurement_status') == 'UNAVAILABLE_LOCAL')
    report.check('counts', result.get('passed_cases') == 5 and result.get('total_cases') == 5)

    progress = client.get(f'/api/v1/courses/{course_id}/my-progress', headers=headers,
                          params={'assignment_id': assignment['id']}).json()
    entry = next(row for row in progress['items'] if row['assignment_item_id'] == item_id)
    report.check('progress passed', entry['has_passed'] is True
                 and entry['best_submission_id'] == receipt['submission_id'])

    history = client.get('/api/v1/me/submissions', headers=headers).json()
    report.check('history', history['total'] == 1 and 'content' not in history['items'][0])

    batch = client.post('/api/v1/me/judge-jobs/status', headers=headers,
                        json={'submission_ids': [receipt['submission_id']]})
    report.check('batch status', batch.status_code == 200
                 and batch.json()['items'][0]['result']['verdict'] == 'ACCEPTED')

    rejudge = client.post(f"/api/v1/submissions/{receipt['submission_id']}/rejudge", headers=headers,
                          json={'client_request_id': uuid.uuid4().hex})
    report.check('rejudge rejected for accepted result', rejudge.status_code == 409, rejudge.text[:120])

    report.check('withdraw after deadline state is stable',
                 client.post(f"/api/v1/submissions/{receipt['submission_id']}/withdraw", headers=headers
                             ).status_code in {200, 409})
    report.check('logout', client.post('/api/v1/auth/logout', headers=headers).status_code == 200)
    report.check('token revoked', client.get('/api/v1/courses', headers=headers).status_code == 401)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='学生作答与评测端到端冒烟检查')
    parser.add_argument('--database', default=os.getenv('DB_NAME', 'algorithm_review_test'))
    parser.add_argument('--reseed', action='store_true', help='清空并重建演示数据（仅限 *_test 库）')
    parser.add_argument('--password', default=os.getenv('SMOKE_PASSWORD'))
    parser.add_argument('--base-url', default=None)
    args = parser.parse_args(argv)

    if args.reseed and not args.database.endswith('_test'):
        parser.error('--reseed 只允许用于名字以 _test 结尾的验证库')
    os.environ['DB_NAME'] = args.database
    password = args.password or secrets.token_urlsafe(24)
    if args.reseed:
        seed(password)

    client_options = {'timeout': 30, 'trust_env': False}
    server = None
    if args.base_url:
        client = httpx.Client(base_url=args.base_url, **client_options)
        report = Report()
        try:
            report.check('health', wait_for(client))
            run_checks(client, report, password)
        finally:
            client.close()
        return report.summary()

    port = free_port()
    env = {**os.environ, **OPERATOR_ENV, 'DB_NAME': args.database}
    server = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1',
                               '--port', str(port), '--log-level', 'warning'],
                              env=env, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    report = Report()
    try:
        with httpx.Client(base_url=f'http://127.0.0.1:{port}', **client_options) as client:
            report.check('server started', wait_for(client))
            run_checks(client, report, password)
    finally:
        if server is not None:
            server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:  # pragma: no cover - defensive
                server.kill()
    return report.summary()


if __name__ == '__main__':
    raise SystemExit(main())
