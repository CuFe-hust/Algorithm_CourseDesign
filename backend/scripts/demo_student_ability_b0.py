"""Persist and execute the chapter B0 meeting demo; never changes passwords or real scores."""
import argparse
import json
import uuid
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.db.session import make_engine
from app.db.models import Course, User
from app.analysis.framework.ability_b0_line import create_batch, project
from app.analysis.framework.service import batch_view
from scripts.demo_analysis import settle


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--course-code',default='DEMO_ALGO')
    args=parser.parse_args()
    engine=make_engine()
    try:
        with Session(engine,expire_on_commit=False) as db:
            teacher=db.scalar(select(User).where(User.login_name=='demo.teacher'))
            course=db.scalar(select(Course).where(Course.code==args.course_code))
            student=db.scalar(select(User).where(User.login_name=='demo.student01'))
            if not all((teacher,course,student)):
                raise SystemExit('Existing synthetic DEMO_ALGO accounts required; seed demo first.')
            created=create_batch(db,course.id,teacher,dict(mode='DEMO',seed=20261029,
                source_batch_id=None,request_id='chapter-b0-'+uuid.uuid4().hex))
            bid=int(created['id']);settle(db,bid)
            view=batch_view(db,bid,teacher);report=project(db,course.id,student,demo=True)
            assert view['status']=='COMPLETE' and report['status']=='OK',view
            print(json.dumps(dict(course_id=str(course.id),batch_id=str(bid),status=view['status'],
                implementation=view['steps'][0]['result']['implementation_name'],is_mock=True,
                input_hash=view['steps'][0]['result']['input_hash'],
                chapter_values=[{k:e[k] for k in ('dimension','value','status','n_items')} for e in report['estimates']],
                demo_url=f'http://127.0.0.1:5173/student/courses/{course.id}/ability?demo=1'),ensure_ascii=True))
    finally:
        engine.dispose()


if __name__=='__main__':main()
