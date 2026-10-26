"""Persist/resume a synthetic analysis batch; never submits actual student grades."""
import argparse
import json
import uuid
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.db.session import make_engine
from app.db.models import Course,User
from app.analysis.framework import service
from app.analysis.framework.runner import process_one
from app.analysis.framework.graph import BY_KEY


def settle(db):
    for _ in range(100):
        if not process_one(db):return
    raise RuntimeError('Worker did not settle within the bounded demonstration.')


def summary(view):
    return {k:view[k] for k in ('id','mode','status','revision_no','is_mock','formal_grade_release')} | {
        'steps':[{'key':s['key'],'status':s['status'],'business_status':s['business_status'],'reason':s['reason']}
                 for s in view['steps']]}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--course-code',default='DEMO_ALGO')
    parser.add_argument('--teacher-login',default='demo.teacher')
    parser.add_argument('--seed',type=int,default=20261026)
    parser.add_argument('--batch-id',type=int)
    parser.add_argument('--event',choices=['OPEN_REVIEW','SUBMIT_REVIEWS','RESOLVE','SUBMIT_SUPPLEMENT','RELEASE'])
    parser.add_argument('--auto-events',action='store_true',help='Explicitly simulate all human gates in DEMO only')
    parser.add_argument('--supplement',action='store_true')
    args=parser.parse_args()
    engine=make_engine()
    try:
        with Session(engine,expire_on_commit=False) as db:
            actor=db.scalar(select(User).where(User.login_name==args.teacher_login))
            course=db.scalar(select(Course).where(Course.code==args.course_code))
            if actor is None or course is None:raise RuntimeError('Seed demo data first.')
            view=service.batch_view(db,args.batch_id,actor) if args.batch_id else service.create_batch(db,course.id,actor,
                dict(mode='DEMO',seed=args.seed,assignment_id=None,assignment_item_id=None,request_id='demo-'+uuid.uuid4().hex))
            if view['mode']!='DEMO':raise RuntimeError('This CLI only advances synthetic DEMO batches.')
            bid=int(view['id']);settle(db);view=service.batch_view(db,bid,actor)
            if args.event:
                view=service.demo_event(db,bid,actor,dict(event=args.event,request_id='cli-'+uuid.uuid4().hex,
                    expected_version=view['revision_no'],action='SUPPLEMENT' if args.supplement else 'KEEP'))
                settle(db);view=service.batch_view(db,bid,actor)
            if args.auto_events:
                for _ in range(8):
                    waiting=next((s for s in view['steps'] if s['status']=='WAITING_HUMAN'),None)
                    if waiting is None:break
                    view=service.demo_event(db,bid,actor,dict(event=BY_KEY[waiting['key']].event,
                        request_id='cli-'+uuid.uuid4().hex,expected_version=view['revision_no'],
                        action='SUPPLEMENT' if args.supplement and waiting['key']=='resolve' else 'KEEP'))
                    settle(db);view=service.batch_view(db,bid,actor)
            print(json.dumps(summary(view),ensure_ascii=True))
    finally:engine.dispose()


if __name__=='__main__':main()
