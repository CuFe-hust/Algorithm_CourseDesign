"""Lock primitives shared by the intake path, the scheduler and recovery.

Advisory keys are declared once here so a namespace collision is a code review
question rather than a data corruption. The per-job lifecycle lock is an OS file
lock: it must work across processes, which a threading.Lock cannot provide.
"""
import fcntl
import os
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import text

from app.judge import config

NAMESPACE = 48121
SCHEDULER_MAIN = (NAMESPACE, 1)
CLAIM = (NAMESPACE, 2)
INTAKE = (NAMESPACE, 3)

DECLARED_KEYS = (SCHEDULER_MAIN, CLAIM, INTAKE)


def check_namespace() -> None:
    assert len(set(DECLARED_KEYS)) == len(DECLARED_KEYS), 'advisory lock keys must stay distinct'
    assert all(first == NAMESPACE for first, _ in DECLARED_KEYS), 'advisory locks share one namespace'


def xact_lock(db, key: tuple[int, int]) -> None:
    db.execute(text('SELECT pg_advisory_xact_lock(:first, :second)'),
               {'first': key[0], 'second': key[1]})


def try_session_lock(connection, key: tuple[int, int]) -> bool:
    return bool(connection.scalar(text('SELECT pg_try_advisory_lock(:first, :second)'),
                                  {'first': key[0], 'second': key[1]}))


def session_unlock(connection, key: tuple[int, int]) -> None:
    connection.execute(text('SELECT pg_advisory_unlock(:first, :second)'),
                       {'first': key[0], 'second': key[1]})


def job_lock_path(job_id: int) -> Path:
    return config.lock_root() / f'{int(job_id)}.lock'


@contextmanager
def job_lock(job_id: int, blocking: bool = True):
    """Exclusive per-job lifecycle lock. The descriptor is close-on-exec by default."""
    path = job_lock_path(job_id)
    fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        flags = fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB)
        fcntl.flock(fd, flags)
        yield
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)
