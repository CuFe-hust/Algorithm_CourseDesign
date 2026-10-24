from sqlalchemy import func, select
from app.db.base import utcnow
from app.db.models import AnalysisJob,Submission,JudgeResult,TestSuite
from app.analysis.contracts import JudgeInput
from app.analysis.judge_mock import judge


def _mock_only():
    """Legacy mock worker: never claim a real LOCAL or LINUX_SANDBOX job."""
    return func.coalesce(AnalysisJob.parameters['execution_mode'].astext, 'MOCK') == 'MOCK'


def process_pending_jobs(session,limit:int=20)->int:
    if not 1<=limit<=1000:raise ValueError('limit must be 1..1000')
    processed=0
    for _ in range(limit):
        job=session.scalar(select(AnalysisJob).where(AnalysisJob.kind=='JUDGE',AnalysisJob.status=='PENDING',
                                                     AnalysisJob.available_at<=utcnow(),_mock_only())
                           .order_by(AnalysisJob.id).with_for_update(skip_locked=True).limit(1))
        if job is None:
            session.commit();break
        sid,jid=job.submission_id,job.id
        submission=session.get(Submission,sid)
        if submission.status=='WITHDRAWN':
            job.status='CANCELLED';job.finished_at=utcnow();session.commit();processed+=1;continue
        job.status='RUNNING';job.started_at=utcnow();session.commit()
        try:
            suite_id=int(job.parameters['test_suite_id'])
            suite=session.get(TestSuite,suite_id)
            if suite is None or suite.status!='FROZEN':
                raise ValueError('Frozen test suite snapshot is unavailable')
            if str(suite.problem_version_id)!=job.parameters.get('problem_version_id',str(suite.problem_version_id)):
                raise ValueError('Test suite and problem snapshot mismatch')
            output=judge(JudgeInput(submission_id=str(sid),source=submission.content,language=submission.language,
                                    test_suite_id=str(suite.id)))
            if not output.is_mock or output.cpu_time_ms is not None or output.memory_kib is not None:
                raise ValueError('mock worker requires an explicitly simulated result')
            job=session.scalar(select(AnalysisJob).where(AnalysisJob.id==jid).with_for_update())
            if job.status!='RUNNING':
                session.rollback();continue
            session.add(JudgeResult(job_id=jid,submission_id=sid,**output.model_dump()))
            job.status='SUCCEEDED';job.finished_at=utcnow();session.commit()
        except Exception:
            session.rollback()
            job=session.get(AnalysisJob,jid)
            if job is not None and job.status=='RUNNING':
                job.status='FAILED';job.error_message='模拟执行失败，请根据任务ID检查本地执行器';job.finished_at=utcnow();session.commit()
        processed+=1
    return processed
