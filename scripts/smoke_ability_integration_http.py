"""Append snapshots to a named LOCAL synthetic course; never closes assignments or changes passwords."""
import argparse
import json
import time
import uuid
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def call(path, token=None, body=None):
    headers={'Content-Type':'application/json'}
    if token:headers['Authorization']='Bearer '+token
    req=Request('http://127.0.0.1:8000/api/v1'+path,headers=headers,
        data=json.dumps(body).encode() if body is not None else None)
    with urlopen(req,timeout=30) as response:return json.load(response)


def denied(path,token,expected):
    try:call(path,token)
    except HTTPError as error:assert error.code==expected
    else:raise AssertionError('Expected permission denial')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--credentials',type=Path,required=True)
    parser.add_argument('--course-id',required=True)
    parser.add_argument('--assignment-id',required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    password=json.loads(args.credentials.read_text())['password']
    def login(name):return call('/auth/login',body=dict(login_name=name,password=password))
    teacher=login('demo.teacher');students=[login(f'demo.student{i:02}') for i in (1,2)]
    token=teacher['access_token'];cid=args.course_id
    courses=call('/courses',token)['items']
    course=next(c for c in courses if str(c['id'])==cid)
    assert course['name']=='算法设计与分析（合成演示）' and course['role']=='TEACHER','Synthetic course required'
    assignment=call(f'/assignments/{args.assignment_id}',token)
    assert assignment['submission_status']=='CLOSED','This check never closes a live assignment'
    fixed=call(f'/analysis/courses/{cid}/question-results',token,
        dict(request_id=uuid.uuid4().hex,assignment_id=args.assignment_id,reason='合成课程：章节分析正式来源联调'))
    body=dict(request_id=uuid.uuid4().hex,source_batch_ids=[fixed['id']],reason='合成课程：固定逐题证据进入B0/D1')
    source=call(f'/analysis/courses/{cid}/course-results',token,body)
    assert call(f'/analysis/courses/{cid}/course-results',token,body)==source
    output=dict(status='passed',data_notice='Synthetic local demo students, real LOCAL judge and reviewed evidence; not real learner validation.',
        course_id=cid,assignment_id=args.assignment_id,question_snapshot=fixed['id'],course_snapshot=source,models={})
    for model,endpoint in [('b0','b0'),('d1','difficulty')]:
        batch=call(f'/analysis/courses/{cid}/student-ability/{endpoint}-batches',token,
            dict(request_id=uuid.uuid4().hex,mode='REAL_INPUT',source_batch_id=source['id']))
        for _ in range(45):
            state=call(f"/analysis/batches/{batch['id']}",token)
            if state['status']=='COMPLETE':break
            assert state['steps'][0]['status']!='FAILED',state['steps'][0].get('reason')
            time.sleep(1)
        assert state['status']=='COMPLETE'
        result=state['steps'][0]['result']
        assert not result['is_mock'] and result['payload']['source_kind']=='DATABASE'
        url=f'/courses/{cid}/my-ability'+('/difficulty' if model=='d1' else '')
        own_keys=[]
        for student in students:
            view=call(url,student['access_token'])
            assert view['status']=='OK' and not view['is_mock']
            assert len(view['estimates'])==11 and view['assignment_count']==1
            keys={e['object_key'] for e in view['estimates']}
            assert len(keys)==1 and all('evidence_item_keys' not in e for e in view['estimates'])
            own_keys.append(keys)
        assert own_keys[0].isdisjoint(own_keys[1])
        demo=call(url+'/demo',students[0]['access_token'])
        assert demo['is_mock'] and demo['source_kind']=='SYNTHETIC_FIXTURE'
        denied(url,token,403)
        denied(f"/analysis/batches/{batch['id']}/input",students[0]['access_token'],403)
        output['models'][model]=dict(batch_id=batch['id'],implementation=result['implementation_name'],
            version=result['implementation_version'],status=result['status'],is_mock=False,
            own_only=True,source_hash=result['input_hash'],converged=result['payload'].get('model_diagnostics',{}).get('converged'))
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(output,ensure_ascii=False))


if __name__=='__main__':main()
