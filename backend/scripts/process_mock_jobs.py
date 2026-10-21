import argparse
import json
import time
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.db.session import make_engine
from app.db.models import AnalysisJob,JudgeResult
from app.analysis.worker import process_pending_jobs


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--limit',type=int,default=20)
    parser.add_argument('--watch',action='store_true')
    parser.add_argument('--recover-running',action='store_true',help='Only use after stopping every old worker.')
    args=parser.parse_args()
    if not 1<=args.limit<=1000:parser.error('--limit must be 1..1000')
    engine=make_engine()
    try:
        with Session(engine,expire_on_commit=False) as session:
            if args.recover_running:
                for job in session.scalars(select(AnalysisJob).where(AnalysisJob.kind=='JUDGE',AnalysisJob.status=='RUNNING')):
                    if session.scalar(select(JudgeResult.id).where(JudgeResult.job_id==job.id)) is None:
                        job.status='PENDING';job.started_at=None
                session.commit()
            while True:
                count=process_pending_jobs(session,args.limit)
                if count or not args.watch:print(json.dumps({'processed':count,'is_mock':True}),flush=True)
                if not args.watch:break
                time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        engine.dispose()


if __name__=='__main__':main()
