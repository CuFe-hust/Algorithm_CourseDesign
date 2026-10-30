"""Live localhost B0 smoke: existing demo credentials stay local; prints no password/token."""
import json
import sys
import uuid
from pathlib import Path
from urllib.request import Request, urlopen
from dotenv import dotenv_values

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))


def request(path,token=None,body=None):
    headers={'Content-Type':'application/json'}
    if token:headers['Authorization']='Bearer '+token
    req=Request('http://127.0.0.1:8000/api/v1'+path,headers=headers,
                data=json.dumps(body).encode() if body is not None else None)
    with urlopen(req,timeout=15) as response:return json.load(response)


def main():
    password=dotenv_values(ROOT/'.env').get('DEMO_PASSWORD')
    if not password:raise SystemExit('Local DEMO_PASSWORD is required; no credentials changed.')
    teacher=request('/auth/login',body={'login_name':'demo.teacher','password':password})['access_token']
    student=request('/auth/login',body={'login_name':'demo.student01','password':password})['access_token']
    course=next(c for c in request('/courses',student)['items'] if c['role']=='STUDENT')
    cid=course['id']
    batch=request(f'/analysis/courses/{cid}/student-ability/b0-batches',teacher,
        {'request_id':'b0-http-'+uuid.uuid4().hex,'mode':'DEMO'})
    from sqlalchemy.orm import Session
    from app.db.session import make_engine
    from scripts.demo_analysis import settle
    engine=make_engine()
    try:
        with Session(engine) as db:settle(db,int(batch['id']))
    finally:engine.dispose()
    report=request(f'/courses/{cid}/my-ability/demo',student)
    formal=request(f'/courses/{cid}/my-ability',student)
    assert report['status']=='OK' and report['is_mock'] is True
    assert formal['status']=='NO_REAL_ANALYSIS' and not formal['estimates']
    assert len(report['estimates'])==11
    assert any(e['status']=='NOT_COVERED' for e in report['estimates'])
    assert any(e['by_type'].get('SUBJECTIVE') for e in report['estimates'])
    print(json.dumps(dict(status='passed',course_id=cid,batch_id=batch['id'],
        formal_status=formal['status'],demo_status=report['status'],
        visible_chapters=sum(e['status']!='NOT_COVERED' for e in report['estimates']),
        implementation='ability_b0',secrets_printed=False),ensure_ascii=True))


if __name__=='__main__':main()
