"""Real localhost teacher -> first login -> published assignment -> LOCAL result.

Run from repository root with the shared API running in LOCAL mode. Creates only
synthetic data in the local demo course. Credentials never enter output or files.
"""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess
import sys
import uuid
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import ProxyHandler, Request, build_opener

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
BASE = sys.argv[1] if len(sys.argv)>1 else 'http://127.0.0.1:8000'
parsed = urlparse(BASE)
if parsed.scheme != 'http' or parsed.hostname not in {'127.0.0.1','localhost'} or parsed.path not in ('','/'):
    raise SystemExit('This synthetic smoke accepts only a localhost HTTP base URL.')
opener = build_opener(ProxyHandler({}))
checks = 0


def api(path, *, token=None, method='GET', body=None, expected=200, raw=None, content_type=None):
    global checks
    headers = {'Content-Type': content_type or 'application/json'}
    if token: headers['Authorization']='Bearer '+token
    payload = raw if raw is not None else json.dumps(body).encode() if body is not None else None
    request = Request(BASE+'/api/v1'+path, data=payload, headers=headers, method=method)
    try:
        with opener.open(request, timeout=15) as response:
            status=response.status; result=json.load(response)
    except HTTPError as error:
        status=error.code; result=json.load(error)
    if status != expected:
        raise AssertionError(f'{method} {path}: expected {expected}, got {status}; code={result.get("code")}')
    checks += 1
    return result


def csv_request(path, content, token, fields=None):
    boundary='teacher-smoke-'+uuid.uuid4().hex
    chunks=[]
    for name,value in (fields or {}).items():
        chunks.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
    chunks.append(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="synthetic.csv"\r\nContent-Type: text/csv\r\n\r\n'.encode()+content+f'\r\n--{boundary}--\r\n'.encode())
    return api(path,token=token,method='POST',raw=b''.join(chunks),content_type='multipart/form-data; boundary='+boundary)


def main():
    global checks
    password=dotenv_values(ROOT/'.env')['DEMO_PASSWORD']
    teacher=api('/auth/login',method='POST',body={'login_name':'demo.teacher','password':password})['access_token']
    course=next(c for c in api('/courses',token=teacher)['items'] if c['role']=='TEACHER' and '合成演示' in c['name'])['id']
    mode=api(f'/teacher/courses/{course}/judge-capabilities',token=teacher)['execution_mode']
    if mode != 'LOCAL': raise SystemExit('Start the API with JUDGE_EXECUTION_MODE=LOCAL for this smoke.')
    number='0099'+uuid.uuid4().hex[:12]
    content=f'student_no,full_name,class_name\n{number},合成联调学生,合成联调班\n'.encode()
    path=f'/teacher/courses/{course}/students/import'
    preview=csv_request(path+'/preview',content,teacher)
    csv_request(path+'/confirm',content,teacher,{'expected_sha256':preview['content_sha256'],'preview_token':preview['preview_token']})
    target=api(f'/teacher/courses/{course}/students?q={number}',token=teacher)['items'][0]
    issued=api(f'/teacher/courses/{course}/students/credentials',token=teacher,method='POST',body={'action':'ACTIVATE','students':[{'student_id':target['id'],'expected_updated_at':target['updated_at']}]})['credentials'][0]
    login=api('/auth/login',method='POST',body={'login_name':issued['login_name'],'password':issued['initial_password']})
    assert login['must_change_password']; student=login['access_token']
    api('/courses',token=student,expected=403)
    changed=api('/auth/change-password',token=student,method='POST',body={'current_password':issued['initial_password'],'new_password':uuid.uuid4().hex})
    api('/auth/session',token=student,expected=401)
    student=changed['access_token'];api('/auth/renew',token=student,method='POST')
    choices=api(f'/teacher/courses/{course}/assignment-choices?limit=100',token=teacher)['items']
    codes=['CODE-P01','SUB-A03','SUB-P01','SUB-O01']
    chosen=[next(c for c in choices if c['code']==code) for code in codes]
    deadline=(datetime.now(timezone.utc)+timedelta(days=3)).isoformat()
    body={'title':'HTTP联调：教师发布与学生作答 '+number[-4:], 'description_md':'仅使用合成身份的端到端验收。',
        'submission_deadline':deadline,'review_deadline':None,'student_ids':[target['id']],
        'items':[{'problem_version_id':c['problem_version_id'],'test_suite_id':c['test_suite_id'],'rubric_id':c['rubric_id'],
                  'required_reviewers':0 if c['test_suite_id'] else 3,'max_score':'100.00','score_weight':'.250000'} for c in chosen]}
    a=api(f'/teacher/courses/{course}/assignments',token=teacher,method='POST',body=body,expected=201)
    api(f"/assignments/{a['id']}",token=student,expected=404)
    a=api(f"/teacher/assignments/{a['id']}/publish",token=teacher,method='POST',body={'expected_updated_at':a['updated_at'],'submission_status':'CLOSED'})
    api(f"/assignments/{a['id']}",token=student)
    item=a['items'][0]
    source='n=int(input())\na=[tuple(map(int,input().split())) for _ in range(n)]\nlast=-1\nans=0\nfor s,t in sorted(a,key=lambda p:(p[1],p[0])):\n if s>=last: last=t; ans+=1\nprint(ans)\n'
    def submit(expected):
        return api(f"/assignment-items/{item['id']}/submissions",token=student,method='POST',body={'client_request_id':str(uuid.uuid4()),'content':source,'language':'python3'},expected=expected)
    submit(409)
    schedule={'expected_updated_at':a['updated_at'],'submission_deadline':deadline,'review_deadline':None,'submission_status':'OPEN'}
    a=api(f"/teacher/assignments/{a['id']}/schedule",token=teacher,method='POST',body=schedule)
    public=api(f"/assignment-items/{item['id']}",token=student)
    assert public['execution_budget']['budget_source']=='LEGACY_DERIVED'
    assert len(public['public_test_cases'])==1 and 'reference_solutions' not in public
    receipt=submit(202)
    # Use the repository's real CLI in another process (not the in-process mock worker).
    import os
    worker=subprocess.run([sys.executable,'-m','scripts.run_judge','--once','--mode','LOCAL'],cwd=ROOT/'backend',
        env={**os.environ,'JUDGE_EXECUTION_MODE':'LOCAL'},capture_output=True,timeout=60)
    if worker.returncode: raise AssertionError('Judge CLI failed; no credential output is emitted.')
    snapshot=api('/submissions/'+receipt['submission_id'],token=student)
    assert snapshot['result']['verdict']=='ACCEPTED' and not snapshot['result']['is_mock']
    assert snapshot['result']['passed_cases']==5 and snapshot['result']['cpu_time_ms'] is None
    own=api(f'/courses/{course}/my-progress?assignment_id='+a['id'],token=student)
    shared=api(f"/teacher/courses/{course}/students/{target['id']}/progress?assignment_id={a['id']}",token=teacher)
    assert own['items']==shared['items'] and shared['items'][0]['effective_submission_id']==receipt['submission_id']
    schedule.update(expected_updated_at=a['updated_at'],submission_status='CLOSED')
    a=api(f"/teacher/assignments/{a['id']}/schedule",token=teacher,method='POST',body=schedule)
    submit(409)
    target=api(f'/teacher/courses/{course}/students?q={number}',token=teacher)['items'][0]
    api(f'/teacher/courses/{course}/students/credentials',token=teacher,method='POST',body={'action':'RESET','students':[{'student_id':target['id'],'expected_updated_at':target['updated_at']}]})
    api('/auth/renew',token=student,method='POST',expected=401)
    api('/auth/logout',token=teacher,method='POST')
    print(f'PASS: {checks} real HTTP checks; LOCAL accepted 5/5, teacher/student candidates identical, old session revoked.')
    print('Synthetic assignment retained as CLOSED:',a['id'])


if __name__=='__main__': main()
