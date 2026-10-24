"""Receive-side protection limits.

Every value has an explicit default; a missing environment value never means
"unlimited". Operators override them per deployment after load testing.
"""
import os


def _int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def login_account_per_minute() -> int:
    return _int('LIMIT_LOGIN_ACCOUNT_PER_MINUTE', 5)


def login_ip_per_minute() -> int:
    return _int('LIMIT_LOGIN_IP_PER_MINUTE', 300)


def login_failure_limit() -> int:
    return _int('LIMIT_LOGIN_FAILURES', 10)


def login_failure_window_seconds() -> int:
    return _int('LIMIT_LOGIN_FAILURE_WINDOW_SECONDS', 600)


def submission_per_minute() -> int:
    return _int('LIMIT_SUBMISSION_PER_MINUTE', 10)


def submission_burst() -> int:
    return _int('LIMIT_SUBMISSION_BURST', 3)


def submission_burst_window_seconds() -> int:
    return _int('LIMIT_SUBMISSION_BURST_WINDOW_SECONDS', 10)


def personal_backlog_limit() -> int:
    return _int('LIMIT_PERSONAL_BACKLOG', 20)


def node_backlog_limit() -> int:
    return _int('LIMIT_NODE_BACKLOG', 200)


def rejudge_cooldown_seconds() -> int:
    return _int('LIMIT_REJUDGE_COOLDOWN_SECONDS', 60)


def rejudge_max_cycles() -> int:
    return _int('LIMIT_REJUDGE_MAX_CYCLES', 3)


def rejudge_per_hour() -> int:
    return _int('LIMIT_REJUDGE_PER_HOUR', 10)


# Route-scoped request body ceilings (bytes). Teacher authoring keeps its own
# generous ceiling so the student limits never shrink existing capabilities.
BODY_LIMITS = (
    ('/api/v1/auth/login', 8 * 1024),
    ('/api/v1/auth/renew', 8 * 1024),
    ('/api/v1/auth/change-password', 8 * 1024),
    ('/api/v1/me/judge-jobs/status', 32 * 1024),
    ('/submissions', 2 * 1024 * 1024),
    ('/submissions/', 2 * 1024 * 1024),
    ('/rejudge', 8 * 1024),
)
DEFAULT_BODY_LIMIT = 16 * 1024 * 1024


def body_limit_for(path: str, method: str = 'POST') -> int:
    if method not in ('POST', 'PUT', 'PATCH'):
        return 64 * 1024
    for suffix, limit in BODY_LIMITS:
        if path.endswith(suffix):
            return limit
    return DEFAULT_BODY_LIMIT
