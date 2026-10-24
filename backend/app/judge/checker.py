"""Deterministic output comparison.

Only the configured ``TEXT_TRIM_TRAILING`` checker exists this round. The
comparison works on bytes: CRLF/CR become LF, ASCII spaces and tabs are removed
at line ends, trailing empty lines are dropped, and everything else (leading and
inner whitespace) must match exactly. Invalid UTF-8 in student output therefore
never raises; it simply fails to match.
"""
import re

_LINE_END = re.compile(rb'[ \t]+(?=\n)')
_TRAILING_NEWLINES = re.compile(rb'\n+\Z')


def normalize(raw: bytes) -> bytes:
    unified = raw.replace(b'\r\n', b'\n').replace(b'\r', b'\n')
    trimmed = _LINE_END.sub(b'', unified)
    return _TRAILING_NEWLINES.sub(b'', trimmed)


def matches(actual: bytes, expected: bytes) -> bool:
    return normalize(actual) == normalize(expected)


def display(raw: bytes, limit: int = 4096) -> str:
    """Decode for public display only; judging always uses the raw bytes."""
    return raw[:limit].decode('utf-8', 'replace')
