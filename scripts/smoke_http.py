"""Exercise the real HTTP API; read local credentials without printing them."""
from pathlib import Path
import argparse
import json
import subprocess
import sys
import uuid
from urllib.request import Request,urlopen
from urllib.error import HTTPError
from dotenv import dotenv_values

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--base-url',default='http://127.0.0.1:8000')
    args=parser.parse_args()
    from urllib.parse import urlparse
    parsed=urlparse(args.base_url)
    if parsed.hostname not in ('127.0.0.1','localhost') or parsed.scheme!='http' or parsed.username or parsed.password:
        parser.error('Demo credentials may only be sent to a local HTTP server.')
    password=dotenv_values(ROOT/'.env').get('DEMO_PASSWORD')
    if not password:raise RuntimeError('Run demo seed first to generate local DEMO_PASSWORD.')
    steps=[]

    def call(path,method='GET',body=None,token=None,expected=200):
        headers={'Content-Type':'application/json'}
        if token:headers['Authorization']='Bearer '+token
        request=Request(args.base_url+'/api/v1'+path,method=method,headers=headers,
                        data=json.dumps(body).encode() if body is not None else None)
        try:
            with urlopen(request,timeout=15) as response:
                status=response.status;data=json.load(response)
        except HTTPError as error:
            status=error.code;data=json.load(error)
        if status!=expected:
            raise RuntimeError(f'HTTP check failed at {method} {path}: {status}, code={data.get("code")}.')
        return data

    def login(name):
        return call('/auth/login','POST',{'login_name':name,'password':password})['access_token']

    call('/ready');steps.append('database_ready')
    student=login('demo.student01');teacher=login('demo.teacher');steps.append('student_teacher_login')
    course=call('/courses',token=student)['items'][0]
    assignments=call('/courses/'+course['id']+'/assignments',token=student)['items']
    item=next(i for a in assignments for i in a['items'] if i['question_type']=='PROGRAMMING')
    question=call('/assignment-items/'+item['id'],token=student)
    assert question['title']=='活动安排问题' and 'reference_solutions' not in question
    steps.append('question_read')
    payload={'content':'print("HTTP联调，不代表真实解答")','language':'python3','client_request_id':'http-'+uuid.uuid4().hex}
    path='/assignment-items/'+item['id']+'/submissions'
    receipt=call(path,'POST',payload,student,202)
    repeated=call(path,'POST',payload,student,202)
    assert receipt['submission_id']==repeated['submission_id'] and repeated['replayed'] is True
    steps.append('submit_and_idempotent_retry')
    done=subprocess.run([sys.executable,'-m','scripts.process_mock_jobs','--limit','1000'],cwd=ROOT/'backend',
                        capture_output=True,text=True,timeout=30)
    if done.returncode:raise RuntimeError('Mock worker failed; no credentials printed.')
    detail=call('/submissions/'+receipt['submission_id'],token=student)
    assert detail['job_status']=='SUCCEEDED' and detail['result']['is_mock'] is True
    assert detail['result']['cpu_time_ms'] is None and detail['result']['memory_kib'] is None
    steps.append('persisted_mock_result')
    another=login('demo.student02')
    call('/submissions/'+receipt['submission_id'],token=another,expected=404)
    listing=call('/teacher/courses/'+course['id']+'/submissions',token=teacher)
    assert any(x['submission_id']==receipt['submission_id'] for x in listing['items'])
    steps.append('teacher_visibility_and_student_isolation')
    subjective=next(i for a in assignments for i in a['items'] if i['question_type']=='PROOF')
    response=call('/assignment-items/'+subjective['id']+'/submissions','POST',
        {'content':'初始化、保持、终止；$right-left$严格减小。','client_request_id':'http-'+uuid.uuid4().hex},student,202)
    assert response['job_status']=='AWAITING_REVIEW'
    steps.append('subjective_answer_stored')
    for token in (student,teacher,another):call('/auth/logout','POST',token=token)
    print(json.dumps({'status':'PASS','transport':'real HTTP','checks':steps,
                      'submission_id':receipt['submission_id'],'mock_verdict':detail['result']['verdict'],
                      'credentials_printed':False},ensure_ascii=True))


if __name__=='__main__':main()
