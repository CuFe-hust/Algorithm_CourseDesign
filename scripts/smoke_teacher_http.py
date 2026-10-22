"""Real local HTTP teacher checks with synthetic data; never print credentials."""
from pathlib import Path
from urllib.parse import urlparse
import argparse
import json
import uuid

import httpx
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--base-url', default='http://127.0.0.1:8000')
    args = parser.parse_args()
    parsed = urlparse(args.base_url)
    if parsed.scheme != 'http' or parsed.hostname not in ('127.0.0.1', 'localhost') or parsed.username or parsed.password:
        parser.error('Demo credentials may only be sent to a local HTTP server.')
    password = dotenv_values(ROOT / '.env').get('DEMO_PASSWORD')
    if not password:
        raise RuntimeError('Run demo seed first; DEMO_PASSWORD must exist locally.')
    run = uuid.uuid4().hex[:12]
    checks = []
    with httpx.Client(base_url=args.base_url + '/api/v1', timeout=20, trust_env=False) as client:
        def call(method, path, token=None, expected=200, **kwargs):
            response = client.request(method, path, headers={'Authorization': 'Bearer ' + token} if token else {}, **kwargs)
            if response.status_code != expected:
                raise RuntimeError(f'{method} {path}: HTTP {response.status_code}; request_id={response.headers.get("x-request-id")}')
            return response.json()

        def login(name):
            return call('POST', '/auth/login', json={'login_name': name, 'password': password})['access_token']

        teacher, student = login('demo.teacher'), login('demo.student01')
        try:
            courses = call('GET', '/courses', teacher)['items']
            course = next(c for c in courses if c['role'] == 'TEACHER' and '合成演示' in c['name'])['id']
            base = f'/teacher/courses/{course}'
            call('GET', base + '/overview', teacher)
            tag = call('POST', base + '/knowledge-points', teacher, 201, json={'name': 'HTTP验收知识点'})
            for kind in ('PROGRAMMING', 'ALGORITHM_ANALYSIS', 'PROOF', 'OPEN_QUESTION'):
                version = {
                    'title': f'HTTP合成验收 {kind}', 'statement_md': '分析 $T(n)=2T(n/2)+n$ 或完成给定任务。',
                    'knowledge_point_ids': [tag['id']],
                    'reference_solutions': [{'content': '合成验收参考答案，仅验证内容持久化与权限。'}],
                }
                if kind == 'PROGRAMMING':
                    version.update(input_spec_md='一个整数', output_spec_md='原样输出',
                        test_suite={'cases': [{'input_text': '1\n', 'expected_output': '1\n', 'weight': '1'}]})
                else:
                    version['rubric'] = {'items': [{'name': '正确性', 'description': '完整推理与边界条件', 'max_score': '100.00'}]}
                first = call('POST', base + '/problems', teacher, 201,
                    json={'code': f'HTTP-{kind[:4]}-{run}', 'question_type': kind, 'version': version})
                path = f"/teacher/problem-versions/{first['id']}"
                edited = call('PUT', path, teacher, json={'expected_updated_at': first['updated_at'], 'version': {**version, 'title': version['title'] + ' 修改'}})
                call('PUT', path, teacher, 409, json={'expected_updated_at': first['updated_at'], 'version': version})
                frozen = call('POST', path + '/freeze', teacher, json={'expected_updated_at': edited['updated_at']})
                assert frozen['status'] == 'FROZEN'
                forked = call('POST', f"/teacher/problems/{first['problem_id']}/versions", teacher, 201, json={'source_version_id': first['id']})
                assert forked['version_no'] == 2 and forked['status'] == 'DRAFT'
                call('GET', path, student, 403)
                call('POST', f"/teacher/problems/{first['problem_id']}/archive", teacher)
            checks.append('four_types_edit_freeze_fork_archive_and_student_denied')
            raw = f'student_no,full_name,class_name\nS{run}1,HTTP合成甲,HTTP合成班\nS{run}2,HTTP合成乙,HTTP合成班\n'.encode('utf-8-sig')
            file = {'file': ('synthetic.csv', raw, 'text/csv')}
            preview = call('POST', base + '/students/import/preview', teacher, files=file)
            assert preview['valid'] and preview['summary']['created_students'] == 2
            assert call('GET', base + f'/students?q=S{run}', teacher)['total'] == 0
            form = {'expected_sha256': preview['content_sha256'], 'preview_token': preview['preview_token']}
            call('POST', base + '/students/import/confirm', teacher, files=file, data=form)
            repeated = call('POST', base + '/students/import/confirm', teacher, files=file, data=form)
            assert repeated['replayed'] is True
            roster = call('GET', base + f'/students?q=S{run}', teacher)
            assert roster['total'] == 2 and all(row['status'] == 'PENDING' for row in roster['items'])
            checks.append('readonly_preview_confirm_pending_and_idempotent_replay')
            call('POST', base + '/students/import/preview', student, 403, files=file)
            checks.append('student_cannot_import')
        finally:
            for token in (teacher, student):
                call('POST', '/auth/logout', token)
    print(json.dumps({'status': 'PASS', 'transport': 'real HTTP', 'checks': checks, 'credentials_printed': False}))


if __name__ == '__main__':
    main()
