"""Single-node scheduler: claim, execute, heartbeat and release.

Only one scheduler process may dispatch at a time (session advisory lock on a
dedicated connection). Each claim takes a short transaction lock, counts occupied
slots (RUNNING including RECOVERING cleanup), picks the oldest eligible job and
registers a new attempt. Execution happens outside that transaction.
"""
from __future__ import annotations

import os
import socket
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import func, select

from app.db.base import utcnow
from app.db.models import AnalysisJob, AssignmentItem, JudgeAttempt, Submission, TestSuite
from app.judge import config, locks, local, results
from app.judge.supervisor import SUPERVISOR, OwnershipLost


@dataclass
class Claim:
    job_id: int
    attempt_id: int
    attempt_no: int
    attempt_token: str
    submission_id: int
    student_id: int
    item_id: int
    source: str
    language: str | None
    test_suite_id: int
    cpu_limit_ms: int


def _mode_filter(mode: str):
    expression = func.coalesce(AnalysisJob.parameters['execution_mode'].astext, config.MOCK)
    return expression == mode


class Scheduler:
    def __init__(self, engine, mode: str | None = None, concurrency: int | None = None):
        from sqlalchemy.orm import sessionmaker
        self.engine = engine
        self.session_factory = sessionmaker(bind=engine, expire_on_commit=False)
        self.mode = (mode or config.execution_mode()).upper()
        if not config.driver_available(self.mode):
            # A missing driver must fail loudly instead of running LOCAL and writing
            # LINUX_SANDBOX into the results.
            raise RuntimeError(f'执行模式 {self.mode} 尚未实现，不能调度')
        self.concurrency = concurrency or config.max_concurrency()
        self.worker_id = f'{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}'
        self._main_connection = None

    # -- main lock ---------------------------------------------------------
    def acquire_main(self) -> bool:
        """Take the exclusive dispatcher lock on a dedicated, non-pooled connection."""
        connection = self.engine.connect().execution_options(isolation_level='AUTOCOMMIT')
        if not locks.try_session_lock(connection, locks.SCHEDULER_MAIN):
            connection.close()
            return False
        self._main_connection = connection
        return True

    def release_main(self) -> None:
        if self._main_connection is not None:
            try:
                locks.session_unlock(self._main_connection, locks.SCHEDULER_MAIN)
            except Exception:  # pragma: no cover - connection already gone
                pass
            self._main_connection.close()
            self._main_connection = None

    @property
    def healthy(self) -> bool:
        if self._main_connection is None:
            return False
        try:
            self._main_connection.scalar(select(func.count()).select_from(AnalysisJob))
            return True
        except Exception:
            return False

    # -- claim -------------------------------------------------------------
    def claim(self) -> Claim | None:
        now = utcnow()
        with self.session_factory() as db:
            locks.xact_lock(db, locks.CLAIM)
            occupied = db.scalar(select(func.count()).select_from(AnalysisJob).where(
                AnalysisJob.kind == 'JUDGE', AnalysisJob.status == 'RUNNING')) or 0
            if occupied >= self.concurrency:
                db.rollback()
                return None
            per_student = dict(db.execute(
                select(Submission.student_id, func.count())
                .join(AnalysisJob, AnalysisJob.submission_id == Submission.id)
                .where(AnalysisJob.kind == 'JUDGE', AnalysisJob.status == 'RUNNING')
                .group_by(Submission.student_id)).all())
            candidates = list(db.scalars(
                select(AnalysisJob)
                .join(Submission, Submission.id == AnalysisJob.submission_id)
                .where(AnalysisJob.kind == 'JUDGE', AnalysisJob.status == 'PENDING',
                       AnalysisJob.available_at <= now, Submission.status != 'WITHDRAWN',
                       _mode_filter(self.mode))
                .order_by(AnalysisJob.available_at, AnalysisJob.id).limit(50)))
            chosen = None
            for job in candidates:
                student_id = db.scalar(select(Submission.student_id).where(Submission.id == job.submission_id))
                if per_student.get(student_id, 0) >= config.per_student_concurrency():
                    continue
                chosen = job
                break
            if chosen is None:
                db.rollback()
                return None
            submission = db.scalar(select(Submission).where(Submission.id == chosen.submission_id)
                                   .with_for_update())
            job = db.scalar(select(AnalysisJob).where(AnalysisJob.id == chosen.id).with_for_update())
            if (submission is None or job is None or submission.status == 'WITHDRAWN'
                    or job.status != 'PENDING' or job.available_at > now):
                db.rollback()
                return None
            attempt_no = job.attempt_no + 1
            token = uuid.uuid4().hex
            attempt = JudgeAttempt(job_id=job.id, attempt_no=attempt_no, status='RUNNING',
                                   execution_mode=self.mode, started_at=now)
            db.add(attempt)
            db.flush()
            job.status = 'RUNNING'
            job.phase = 'COMPILING'
            job.attempt_no = attempt_no
            job.attempt_token = token
            job.owner_id = self.worker_id
            job.started_at = job.started_at or now
            job.heartbeat_at = now
            job.lease_expires_at = now + timedelta(seconds=config.LEASE_SECONDS)
            item = db.get(AssignmentItem, submission.assignment_item_id)
            suite_id = (job.parameters or {}).get('test_suite_id')
            suite = db.get(TestSuite, int(suite_id)) if suite_id is not None else None
            claim = Claim(job_id=job.id, attempt_id=attempt.id, attempt_no=attempt_no, attempt_token=token,
                          submission_id=submission.id, student_id=submission.student_id,
                          item_id=submission.assignment_item_id, source=submission.content,
                          language=submission.language,
                          test_suite_id=int(suite_id) if suite_id is not None else 0,
                          cpu_limit_ms=suite.cpu_limit_ms if suite else 1000)
            db.commit()
            return claim

    # -- execution ---------------------------------------------------------
    def _verify(self, job_id: int, token: str):
        def check() -> bool:
            with self.session_factory() as db:
                row = db.execute(select(AnalysisJob.status, AnalysisJob.attempt_token, AnalysisJob.phase,
                                        AnalysisJob.lease_expires_at)
                                 .where(AnalysisJob.id == job_id)).first()
                if row is None:
                    return False
                status, current, phase, lease = row
                return (status == 'RUNNING' and current == token and phase != 'RECOVERING'
                        and lease is not None and lease > utcnow())
        return check

    def _heartbeat(self, job_id: int, token: str, stop: threading.Event, lost: threading.Event):
        while not stop.wait(config.HEARTBEAT_SECONDS):
            try:
                with self.session_factory() as db:
                    now = utcnow()
                    updated = db.execute(
                        AnalysisJob.__table__.update()
                        .where(AnalysisJob.id == job_id, AnalysisJob.attempt_token == token,
                               AnalysisJob.status == 'RUNNING')
                        .values(heartbeat_at=now,
                                lease_expires_at=now + timedelta(seconds=config.LEASE_SECONDS)))
                    db.commit()
                    if updated.rowcount == 0:
                        lost.set()
                        SUPERVISOR.terminate(job_id)
                        return
            except Exception:
                # Database temporarily unavailable: keep the local lease running until it expires.
                continue

    def execute(self, claim: Claim) -> str:
        stop = threading.Event()
        lost = threading.Event()
        heartbeat = threading.Thread(target=self._heartbeat,
                                     args=(claim.job_id, claim.attempt_token, stop, lost), daemon=True)
        heartbeat.start()
        outcome = None
        error: Exception | None = None
        try:
            with self.session_factory() as db:
                cases = results.case_inputs(db, claim.test_suite_id)
            outcome = SUPERVISOR.run(claim.job_id, claim.attempt_token,
                                     self._verify(claim.job_id, claim.attempt_token),
                                     claim.source, claim.language or '', cases, claim.cpu_limit_ms)
        except OwnershipLost:
            stop.set()
            return 'aborted'
        except local.ConfigurationError as failure:
            error = failure
        except local.InfrastructureError as failure:
            error = failure
        except Exception as failure:  # noqa: BLE001 - classified as a facility failure
            error = local.InfrastructureError(f'执行设施异常：{type(failure).__name__}')
        finally:
            stop.set()
            heartbeat.join(timeout=5)
        if lost.is_set():
            return 'aborted'
        with self.session_factory() as db:
            if error is not None:
                retryable = isinstance(error, local.InfrastructureError)
                code = getattr(error, 'code', 'JUDGE_FACILITY_FAILURE')
                return results.record_failure(db, claim.job_id, claim.attempt_token, code,
                                              str(error), retryable=retryable)
            if outcome is None:
                return 'aborted'
            saved = results.record_success(db, claim.job_id, claim.attempt_token, outcome, self.mode,
                                           config.runtime_profile(self.mode))
            return 'succeeded' if saved is not None else 'aborted'

    # -- loops -------------------------------------------------------------
    def run_once(self) -> int:
        from concurrent.futures import ThreadPoolExecutor
        started = 0
        with ThreadPoolExecutor(max_workers=self.concurrency) as pool:
            futures = []
            while started < self.concurrency:
                claim = self.claim()
                if claim is None:
                    break
                futures.append(pool.submit(self.execute, claim))
                started += 1
            for future in futures:
                future.result()
        return started

    def run_forever(self, stop: threading.Event, poll_seconds: float = 1.0):  # pragma: no cover - loop
        if not self.acquire_main():
            raise RuntimeError('another scheduler already holds the node dispatch lock')
        try:
            while not stop.is_set():
                if not self.healthy:
                    break
                if self.run_once() == 0:
                    stop.wait(poll_seconds)
        finally:
            self.release_main()
