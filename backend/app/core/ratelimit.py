"""Cross-process fixed-window counters shared by every API worker.

Counters live in PostgreSQL so two API processes cannot both grant the same quota.
Each row is bounded by its window and carries its own expiry, so the auxiliary
cleanup job can drop expired buckets without touching business idempotency rows.
"""
import hashlib
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.base import utcnow
from app.db.models import RequestRateLimit

_SALT = 'algoclass-rate-limit-v1'


def subject_key(value: str) -> str:
    """Return a stable, non-reversible subject key (no raw IP or login name stored)."""
    return hashlib.sha256(f'{_SALT}:{value}'.encode()).hexdigest()


def _window_start(now: datetime, seconds: int) -> datetime:
    epoch = int(now.timestamp() // seconds) * seconds
    return datetime.fromtimestamp(epoch, timezone.utc)


def hit(db: Session, bucket: str, subject: str, limit: int, window_seconds: int,
        now: datetime | None = None) -> tuple[bool, int, datetime]:
    """Count one hit and report whether it stays within the quota.

    Returns ``(allowed, remaining, retry_after_at)``. The increment is a single
    upsert statement, so concurrent connections serialize on the row instead of
    reading and then writing a stale value.
    """
    now = now or utcnow()
    start = _window_start(now, window_seconds)
    expires = start + timedelta(seconds=window_seconds + 60)
    table = RequestRateLimit.__table__
    statement = (pg_insert(RequestRateLimit)
                 .values(bucket=bucket, subject_hash=subject, window_start=start, window_seconds=window_seconds,
                         counter=1, expires_at=expires)
                 .on_conflict_do_update(
                     index_elements=['bucket', 'subject_hash', 'window_start', 'window_seconds'],
                     set_={'counter': table.c.counter + 1, 'expires_at': expires})
                 .returning(table.c.counter))
    counter = db.scalar(statement)
    retry_after_at = start + timedelta(seconds=window_seconds)
    return counter <= limit, max(0, limit - counter), retry_after_at


def peek(db: Session, bucket: str, subject: str, window_seconds: int,
         now: datetime | None = None) -> tuple[int, datetime]:
    """Read the current window counter without consuming quota."""
    now = now or utcnow()
    start = _window_start(now, window_seconds)
    counter = db.scalar(select(RequestRateLimit.counter).where(
        RequestRateLimit.bucket == bucket, RequestRateLimit.subject_hash == subject,
        RequestRateLimit.window_start == start, RequestRateLimit.window_seconds == window_seconds)) or 0
    return counter, start + timedelta(seconds=window_seconds)


def enforce(db: Session, bucket: str, subject: str, limit: int, window_seconds: int,
            code: str = 'RATE_LIMITED', message: str = '操作过于频繁，请稍后再试',
            now: datetime | None = None) -> None:
    allowed, _, retry_after_at = hit(db, bucket, subject, limit, window_seconds, now)
    if allowed:
        return
    db.commit()
    retry_after = max(1, int((retry_after_at - (now or utcnow())).total_seconds()))
    raise AppError(429, code, message, {'retry_after_at': retry_after_at.isoformat()},
                   headers={'Retry-After': str(retry_after)})


def purge_expired(db: Session, now: datetime | None = None, batch: int = 5000) -> int:
    """Delete a bounded batch of expired counters (auxiliary data, never history)."""
    now = now or utcnow()
    deleted = 0
    while deleted < batch:
        rows = list(db.scalars(select(RequestRateLimit).where(RequestRateLimit.expires_at < now).limit(
            min(500, batch - deleted))))
        if not rows:
            break
        for row in rows:
            db.delete(row)
        db.commit()
        deleted += len(rows)
    return deleted
