import argparse
import json
import os
import secrets
from datetime import timedelta
from dotenv import dotenv_values, set_key
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.config import ROOT
from app.db.session import make_engine
from app.db.base import utcnow
from app.db.models import Course, Assignment
from app.demo import seed_demo


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--deadline-days', type=int, default=7)
    parser.add_argument('--refresh-deadlines', action='store_true')
    args = parser.parse_args()
    if not 1 <= args.deadline_days <= 365:
        parser.error('--deadline-days must be 1..365')
    path = ROOT / '.env'
    values = dotenv_values(path)
    password = os.getenv('DEMO_PASSWORD') or values.get('DEMO_PASSWORD')
    if not password:
        password = secrets.token_urlsafe(24)
        set_key(str(path), 'DEMO_PASSWORD', password)
    engine = make_engine()
    with Session(engine) as session:
        summary = seed_demo(session, password, args.deadline_days)
        if args.refresh_deadlines:
            course_id = session.scalar(select(Course.id).where(Course.code=='DEMO_ALGO'))
            for a in session.scalars(select(Assignment).where(Assignment.course_id==course_id)):
                a.submission_deadline = utcnow()+timedelta(days=args.deadline_days)
                if a.review_deadline is not None:
                    a.review_deadline = a.submission_deadline+timedelta(days=2)
            session.commit()
        print(json.dumps({'status':'ready', 'demo':summary, 'password_location':'.env:DEMO_PASSWORD'}, ensure_ascii=True))
    engine.dispose()


if __name__ == '__main__':
    main()
