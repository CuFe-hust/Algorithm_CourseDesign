"""Bounded auxiliary-data cleanup (RV09).

Only auxiliary data is touched: expired sessions, shared throttle buckets and
compiler diagnostics past their retention window. Submissions, verdicts, pass
counts, attempts and idempotency records are never deleted here.
"""
from __future__ import annotations

import os
from datetime import timedelta

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import utcnow
from app.db.models import AuthSession, JudgeResult, RequestRateLimit


def _int(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, ''))
    except ValueError:
        return default
    return value if value > 0 else default


def retention_days() -> int:
    return _int('JUDGE_DIAGNOSTIC_RETENTION_DAYS', 30)


def purge_sessions(db: Session, now=None, batch: int = 2000) -> int:
    now = now or utcnow()
    expired = list(db.scalars(select(AuthSession.id).where(
        AuthSession.expires_at < now - timedelta(hours=24)).limit(batch)))
    if expired:
        db.execute(delete(AuthSession).where(AuthSession.id.in_(expired)))
        db.commit()
    return len(expired)


def purge_rate_limits(db: Session, now=None, batch: int = 5000) -> int:
    now = now or utcnow()
    expired = list(db.scalars(select(RequestRateLimit.id).where(
        RequestRateLimit.expires_at < now).limit(batch)))
    if expired:
        db.execute(delete(RequestRateLimit).where(RequestRateLimit.id.in_(expired)))
        db.commit()
    return len(expired)


def expire_diagnostics(db: Session, now=None, batch: int = 200) -> int:
    """Blank old compiler diagnostics while keeping the verdict and counts intact."""
    now = now or utcnow()
    cutoff = now - timedelta(days=retention_days())
    rows = list(db.scalars(select(JudgeResult.id).where(
        JudgeResult.compiler_message.isnot(None),
        JudgeResult.diagnostics_expired_at.is_(None),
        JudgeResult.created_at < cutoff).limit(batch)))
    if rows:
        db.execute(update(JudgeResult).where(JudgeResult.id.in_(rows))
                   .values(compiler_message=None, diagnostics_expired_at=now))
        db.commit()
    return len(rows)


def purge_all(engine, now=None) -> dict:
    now = now or utcnow()
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        return {'sessions': purge_sessions(db, now),
                'rate_limits': purge_rate_limits(db, now),
                'diagnostics': expire_diagnostics(db, now)}


def diagnostics_bytes(db: Session) -> int:
    return db.scalar(select(func.coalesce(func.sum(func.length(JudgeResult.compiler_message)), 0))) or 0
