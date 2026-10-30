"""Actual localhost D1 read/create/worker isolation checks. No credentials printed."""
import json
import uuid
from dotenv import dotenv_values
from smoke_ability_b0_http import ROOT,request


def main():
    password=dotenv_values(ROOT/'.env').get('DEMO_PASSWORD')
    if not password:raise SystemExit('Local demo password unavailable.')
    teacher=request('/auth/login',body={'login_name':'demo.teacher','password':password})['access_token']
    student=request('/auth/login',body={'login_name':'demo.student01','password':password})['access_token']
    cid=next(c['id'] for c in request('/courses',student)['items'] if c['role']=='STUDENT')
    batch=request(f'/analysis/courses/{cid}/student-ability/difficulty-batches',teacher,
                  {'mode':'DEMO','request_id':'difficulty-http-'+uuid.uuid4().hex})
    from app.db.session import make_engine
    from sqlalchemy.orm import Session
    from scripts.demo_analysis import settle
    engine=make_engine()
    try:
        with Session(engine) as db:settle(db,int(batch['id']))
    finally:engine.dispose()
    before=request(f"/analysis/batches/{batch['id']}/input",teacher)
    report=request(f'/courses/{cid}/my-ability/difficulty/demo',student)
    assert report['status']=='OK' and report['is_mock'] and report['model_diagnostics']['converged']
    assert report['model_parameters']==before['payload']['model_parameters']
    assert len(report['estimates'])==11 and report['process_diagnostics']['available']
    assert request(f'/courses/{cid}/my-ability/difficulty',student)['status']=='NO_REAL_ANALYSIS'
    print(json.dumps(dict(status='passed',batch_id=batch['id'],course_id=cid,
        method=report['method'],converged=report['model_diagnostics']['converged'],
        parameters_frozen=True,process_items=len(report['process_diagnostics']['items']),credentials_printed=False)))


if __name__=='__main__':main()
