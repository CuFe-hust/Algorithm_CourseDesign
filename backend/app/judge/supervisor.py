"""The single lifecycle authority for starting, terminating and cleaning executions.

Every local execution goes through :class:`ExecutionSupervisor`. Before the
student program is allowed to run, the supervisor holds the per-job OS lock,
re-verifies ownership against a fresh database read, and only then opens the
start gate. A recovery pass that wins the lock first revokes the token, so a
late starter fails verification and never runs.
"""
from __future__ import annotations

import json
import os
import signal
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from app.judge import config, local, locks
from app.judge.local import OwnershipLost

__all__ = ['ExecutionSupervisor', 'SUPERVISOR', 'OwnershipLost', 'Marker', 'marker_path', 'read_marker',
           'terminate_marker']


@dataclass
class Marker:
    job_id: int
    attempt_token: str
    pid: int
    pgid: int
    started_at: float

    def to_json(self) -> str:
        return json.dumps({'job_id': self.job_id, 'attempt_token': self.attempt_token, 'pid': self.pid,
                           'pgid': self.pgid, 'started_at': self.started_at})


def marker_path(job_id: int) -> Path:
    return config.work_root() / f'exec-{int(job_id)}.json'


def read_marker(job_id: int) -> Marker | None:
    path = marker_path(job_id)
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        return Marker(**data)
    except (OSError, ValueError, TypeError):
        return None


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def terminate_marker(marker: Marker) -> bool:
    """Terminate the process group recorded for an execution. Returns True if it was signalled."""
    signalled = False
    if marker.pgid and marker.pgid > 1:
        try:
            os.killpg(marker.pgid, signal.SIGKILL)
            signalled = True
        except ProcessLookupError:
            pass
        except PermissionError:  # pragma: no cover - defensive
            return False
    if _pid_alive(marker.pid):
        try:
            os.kill(marker.pid, signal.SIGKILL)
            signalled = True
        except ProcessLookupError:
            pass
    return signalled


class ExecutionSupervisor:
    """Tracks the executions owned by this process and gates every start."""

    def __init__(self):
        self._lock = threading.Lock()
        self._running: dict[int, local.Spawned] = {}

    def gate(self, job_id: int, attempt_token: str, verify: Callable[[], bool],
             lock_timeout: float = 30.0) -> local.Gate:
        def _gate(spawned: local.Spawned) -> bool:
            deadline = time.monotonic() + lock_timeout
            while True:
                try:
                    with locks.job_lock(job_id, blocking=False):
                        if not verify():
                            raise OwnershipLost('job ownership changed before start')
                        with self._lock:
                            self._running[job_id] = spawned
                        marker = Marker(job_id=job_id, attempt_token=attempt_token, pid=spawned.process.pid,
                                        pgid=spawned.pgid, started_at=spawned.started_at)
                        marker_path(job_id).write_text(marker.to_json(), encoding='utf-8')
                        # Re-verify inside the same critical section, after registration.
                        if not verify():
                            marker_path(job_id).unlink(missing_ok=True)
                            with self._lock:
                                self._running.pop(job_id, None)
                            raise OwnershipLost('job ownership changed during registration')
                        return True
                except BlockingIOError:
                    if time.monotonic() > deadline:
                        raise OwnershipLost('lifecycle lock is held by another process')
                    time.sleep(0.01)
        return _gate

    def release_job(self, job_id: int) -> None:
        with self._lock:
            self._running.pop(job_id, None)
        marker_path(job_id).unlink(missing_ok=True)

    def terminate(self, job_id: int) -> bool:
        """Terminate a locally registered execution; falls back to the on-disk marker."""
        with self._lock:
            spawned = self._running.get(job_id)
        if spawned is not None:
            local.terminate(spawned)
            self.release_job(job_id)
            return True
        marker = read_marker(job_id)
        if marker is None:
            return False
        terminate_marker(marker)
        marker_path(job_id).unlink(missing_ok=True)
        return True

    def run(self, job_id: int, attempt_token: str, verify: Callable[[], bool], source: str,
            language: str, cases: list[local.CaseInput], cpu_limit_ms: int) -> local.ExecutionOutcome:
        try:
            return local.execute(source, language, cases, cpu_limit_ms,
                                 gate=self.gate(job_id, attempt_token, verify))
        finally:
            self.release_job(job_id)


SUPERVISOR = ExecutionSupervisor()
