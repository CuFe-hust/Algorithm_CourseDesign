"""The complexity classes the platform can report, and their growth bases.

Every class is a growth function ``f(n)`` used by the least-squares fit and by
the chart. The order of :data:`TIME_CLASSES` is the order used to compare two
classes: a larger index means a faster-growing class. ``O(n!)`` is included
because the trace route can separate factorial from exponential growth (a
permutation generator and a naive recursive Fibonacci program differ by more
than any constant factor within a few rungs), while the wall-clock route could
not express it.

The space list stays short on purpose: peak allocation grows like a constant, a
logarithm, a linear term or a square in practically every accepted program, and
none of the memory data sources count the call stack exactly.
"""

from __future__ import annotations

import math

TIME_CLASSES = ('O(1)', 'O(log n)', 'O(n)', 'O(n log n)', 'O(n^2)', 'O(n^2 log n)',
                'O(n^3)', 'O(2^n)', 'O(n!)')
SPACE_CLASSES = ('O(1)', 'O(log n)', 'O(n)', 'O(n^2)')
CLASS_RANK = {name: index for index, name in enumerate(TIME_CLASSES)}

CONFIDENCE = ('LOW', 'MEDIUM', 'HIGH')


def _log2(n: float) -> float:
    return math.log2(n) if n > 1 else 0.0


def _exp2(n: int) -> float:
    # The ladder never reaches large n for exponential programs; the ceiling is
    # only here so a malformed ladder cannot overflow.
    return 2.0 ** min(int(n), 100)


def _factorial(n: int) -> float:
    if n < 1:
        return 1.0
    if n > 170:
        return float('inf')
    return float(math.factorial(int(n)))


GROWTH_FUNCTIONS = {
    'O(1)': lambda n: 1.0,
    'O(log n)': lambda n: _log2(n),
    'O(n)': lambda n: float(n),
    'O(n log n)': lambda n: n * _log2(n),
    'O(n^2)': lambda n: float(n) ** 2,
    'O(n^2 log n)': lambda n: (float(n) ** 2) * _log2(n),
    'O(n^3)': lambda n: float(n) ** 3,
    'O(2^n)': _exp2,
    'O(n!)': _factorial,
}


def rank(name: str | None) -> int:
    return CLASS_RANK.get(name or '', -1)


def greater(left: str | None, right: str | None) -> str:
    """The faster growing of two classes; ``UNKNOWN`` only when both are unknown."""
    if left not in CLASS_RANK:
        return right if right in CLASS_RANK else 'UNKNOWN'
    if right not in CLASS_RANK:
        return left
    return left if CLASS_RANK[left] >= CLASS_RANK[right] else right


def next_class(name: str) -> str:
    position = CLASS_RANK.get(name)
    if position is None:
        return 'UNKNOWN'
    return TIME_CLASSES[min(position + 1, len(TIME_CLASSES) - 1)]


def class_at_least(name: str, floor: str) -> str:
    return greater(name, floor)


def is_known(name: str | None) -> bool:
    return name in CLASS_RANK


def describe_exponent(value: float) -> str:
    """Name the smallest class whose growth is at least ``n ** value``.

    Recursive solutions occasionally produce a fractional exponent (Karatsuba's
    1.585): the vocabulary cannot express it exactly, so the report states the
    derived form and the smallest class that bounds it. ``O(n!)`` is never used
    as a bound here because a polynomial is always below the previous class.
    """
    for name in ('O(1)', 'O(log n)', 'O(n)', 'O(n log n)', 'O(n^2)', 'O(n^2 log n)', 'O(n^3)'):
        if value <= _expected_exponent(name) + 1e-9:
            return name
    return 'O(2^n)'


def _expected_exponent(name: str) -> float:
    return {'O(1)': -1.0, 'O(log n)': 0.0, 'O(n)': 1.0, 'O(n log n)': 1.0,
            'O(n^2)': 2.0, 'O(n^2 log n)': 2.0, 'O(n^3)': 3.0}.get(name, 3.0)
