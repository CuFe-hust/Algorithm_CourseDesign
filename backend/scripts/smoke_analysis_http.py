"""Real HTTP test of teacher-only synthetic analysis. Never prints secrets."""
import argparse
import json
import uuid
import httpx
from dotenv import dotenv_values
from sqlalchemy.orm import Session
from app.core.config import ROOT
from app.db.session import make_engine
from scripts.demo_analysis import settle as settle_batch


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url',default='http://127.0.0.1:8000')
    args=parser.parse_args();values=dotenv_values(ROOT/'.env');engine=make_engine()
    try:
        with httpx.Client(base_url=args.base_url,timeout=20) as client:
            def login(name):
                response=client.post('/api/v1/auth/login',json={'login_name':name,'password':values['DEMO_PASSWORD']})
                assert response.status_code==200,'Demo login failed'
                return {'Authorization':'Bearer '+response.json()['access_token']}
            teacher=login('demo.teacher');student=login('demo.student01')
            assert client.get('/api/v1/ready').json()['migration']=='pg0006'
            courses=client.get('/api/v1/courses',headers=teacher).json()['items']
            course=next(c for c in courses if '合成演示' in c['name'])
            assert len(client.get('/api/v1/analysis/catalog',headers=teacher).json()['items'])==15
            response=client.post(f"/api/v1/analysis/courses/{course['id']}/batches",headers=teacher,
                json={'mode':'DEMO','seed':20261026,'request_id':'http-smoke-'+uuid.uuid4().hex})
            assert response.status_code==201,response.text
            bid=response.json()['id'];url=f'/api/v1/analysis/batches/{bid}'
            assert client.get(url,headers=student).status_code==403
            def settle():
                with Session(engine) as db:
                    settle_batch(db,int(bid))
                result=client.get(url,headers=teacher);assert result.status_code==200
                return result.json()
            view=settle()
            for event in ('OPEN_REVIEW','SUBMIT_REVIEWS','RESOLVE','SUBMIT_SUPPLEMENT'):
                response=client.post(url+'/demo-events',headers=teacher,json=dict(event=event,
                    request_id='http-'+uuid.uuid4().hex,expected_version=view['revision_no'],
                    action='SUPPLEMENT' if event=='RESOLVE' else 'KEEP'))
                assert response.status_code==200,response.text
                view=settle()
            assert view['status']=='COMPLETE' and view['is_mock']
            assert all(s['status']=='SUCCEEDED' for s in view['steps'])
            assert all(s['result']['is_mock'] for s in view['steps'])
            print(json.dumps(dict(status='PASS',transport='real HTTP',batch_id=bid,steps=len(view['steps']),
                catalogue=15,student_denied=True,supplement_path=True,is_mock=True,
                credentials_printed=False)))
    finally:engine.dispose()


if __name__=='__main__':main()
