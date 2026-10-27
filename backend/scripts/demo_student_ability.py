"""Run sixth line independently; uses the existing ability placeholder unchanged."""
import argparse
import json
import uuid
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.db.session import make_engine
from app.db.models import Course,User
from app.analysis.framework.service import create_ability_batch,batch_view,ability_input_view
from scripts.demo_analysis import settle


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--course-code',default='DEMO_ALGO')
    parser.add_argument('--mode',choices=['DEMO','REAL_INPUT'],default='DEMO')
    parser.add_argument('--source-batch-id',type=int)
    parser.add_argument('--seed',type=int,default=20261026)
    args=parser.parse_args();engine=make_engine()
    try:
        with Session(engine) as db:
            actor=db.scalar(select(User).where(User.login_name=='demo.teacher'))
            course=db.scalar(select(Course).where(Course.code==args.course_code))
            if actor is None or course is None:raise SystemExit('Seed demo data first.')
            result=create_ability_batch(db,course.id,actor,dict(mode=args.mode,seed=args.seed,
                source_batch_id=str(args.source_batch_id) if args.source_batch_id else None,
                request_id='sixth-line-'+uuid.uuid4().hex))
            bid=int(result['id']);settle(db,bid)
            result=batch_view(db,bid,actor);source=ability_input_view(db,bid,actor)
            print(json.dumps(dict(batch_id=str(bid),pipeline=result['pipeline'],status=result['status'],
                is_mock=result['is_mock'],input_snapshot_id=source['snapshot_id'],input_hash=source['input_hash'],
                source=source['source'],input_records=len(source['payload']['grades']) if source['payload'] else 0,
                black_box=result['steps'][0]),ensure_ascii=True))
    finally:engine.dispose()


if __name__=='__main__':main()
