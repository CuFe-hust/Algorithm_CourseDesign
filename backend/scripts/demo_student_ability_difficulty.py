"""Persist D1 with validation-selected parameters and real optimization, on labeled demo inputs."""
import json
import uuid
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.db.session import make_engine
from app.db.models import Course,User
from app.analysis.framework.ability_b0_line import create_batch,project
from app.analysis.framework.service import batch_view
from scripts.demo_analysis import settle


def main():
    engine=make_engine()
    try:
        with Session(engine,expire_on_commit=False) as db:
            teacher=db.scalar(select(User).where(User.login_name=='demo.teacher'))
            student=db.scalar(select(User).where(User.login_name=='demo.student01'))
            course=db.scalar(select(Course).where(Course.code=='DEMO_ALGO'))
            if not all((teacher,student,course)):
                raise SystemExit('Existing synthetic demo accounts required; no credentials changed.')
            batch=create_batch(db,course.id,teacher,dict(mode='DEMO',seed=20261029,source_batch_id=None,
                request_id='difficulty-demo-'+uuid.uuid4().hex),model='d1')
            bid=int(batch['id']);settle(db,bid)
            saved=batch_view(db,bid,teacher);report=project(db,course.id,student,demo=True,model='d1')
            assert saved['status']=='COMPLETE' and report['status']=='OK',saved
            assert report['model_diagnostics']['converged'],report['model_diagnostics']
            print(json.dumps(dict(batch_id=str(bid),course_id=str(course.id),status=saved['status'],
                implementation=saved['steps'][0]['result']['implementation_name'],is_mock=True,
                parameters=report['model_parameters'],diagnostics=report['model_diagnostics'],
                estimates=[{k:e[k] for k in ('dimension','value','baseline_value','status')} for e in report['estimates']],
                demo_url=f'http://127.0.0.1:5173/student/courses/{course.id}/ability?demo=1&model=d1'),ensure_ascii=True))
    finally:engine.dispose()


if __name__=='__main__':main()
