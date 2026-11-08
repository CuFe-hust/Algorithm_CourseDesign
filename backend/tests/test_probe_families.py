"""Tests for the input-synthesis families that give problems a scalable input.

Two properties matter for every generator. The same family, seed and spec must
produce byte-identical text, because a stored report has to be reproducible
later. And the generated text must be readable by the problem's own reference
solution: a format mismatch would measure the program's error path instead of
its algorithm, which is exactly the bug this table was rewritten to remove.

The reference-solution cases run a single rung each on purpose; the whole file
stays in the low seconds. Full 70-problem acceptance is the offline script
``scripts/validate_complexity_profiles.py``.
"""
import json
import time

import pytest

from app.analysis import probe
from app.analysis.profiles import NOT_SCALABLE, PROFILES, QUESTION_BANK
from app.analysis.trace.adapters import python_adapter

SEED = 20261028

# Families added (or given new spec options) when the route switched to counted
# execution traces. Each one describes a concrete input format read by the bank's
# own reference solutions.
COVERAGE_FAMILIES = (
    'THREE_INTS', 'INT_ARRAY_WITH_K', 'SORTED_ARRAY_QUERIES',
    'INT_ARRAY_OPERATIONS', 'TWO_INT_ARRAYS', 'INT_ARRAY_ROWS_TWO_HEADER',
    'GRAPH_TREE_QUERIES', 'GRAPH_EDGE_QUERIES', 'GRAPH_COLORING',
    'BIG_TWO_STRINGS', 'STRING_LIST', 'STRING_RANGE_QUERIES',
    'POSTFIX_EXPRESSION', 'STACK_OPERATIONS', 'GRID_WITH_WORD',
    'TRIANGLE_ROWS', 'KNAPSACK',
)

# One representative problem per tricky format: values spread over the triangle
# rows, the separate query-count line, a simple graph with u < v, a string
# followed by position queries, alternating update/query operations, and range
# rows where l <= r matters.
REFERENCE_CASES = ('CODE-P20', 'CODE-P32', 'CODE-P38', 'CODE-P45', 'CODE-P54', 'CODE-P70')

BANK = {entry['code']: entry.get('reference_solutions') or []
        for entry in json.loads(QUESTION_BANK.read_text(encoding='utf-8'))}


def _sample_spec(family: str) -> dict:
    """The spec the seeded profiles use for this family (first problem wins)."""
    for candidate, spec in PROFILES.values():
        if candidate == family:
            return dict(spec)
    raise AssertionError(f'{family} 没有对应的种子伸缩档，无法取样')


def test_every_profile_names_a_known_family():
    assert all(family in probe.FAMILIES for family, _ in PROFILES.values())
    assert all(code in BANK for code in PROFILES)
    # A code listed as not scalable has to carry the family that says so.
    assert all(PROFILES[code][0] == 'FIXED' for code in NOT_SCALABLE)
    assert all(code in PROFILES for code in NOT_SCALABLE)


@pytest.mark.parametrize('family', COVERAGE_FAMILIES)
def test_generation_is_deterministic(family):
    spec = _sample_spec(family)
    first = probe.generate(family, 64, SEED, spec)
    second = probe.generate(family, 64, SEED, spec)
    assert first
    assert first == second
    assert probe.generate(family, 64, SEED + 1, spec) == probe.generate(family, 64, SEED + 1, spec)


@pytest.mark.parametrize('family', COVERAGE_FAMILIES)
def test_ladder_is_reproducible(family):
    spec = _sample_spec(family)
    first = probe.ladder(family, SEED, spec)
    second = probe.ladder(family, SEED, spec)
    assert len(first) >= 3
    assert [(rung.n, rung.input_text) for rung in first] == \
           [(rung.n, rung.input_text) for rung in second]
    assert [rung.n for rung in first] == sorted(rung.n for rung in first)


@pytest.mark.parametrize('family', COVERAGE_FAMILIES)
def test_ladder_shrinks_with_max_n(family):
    spec = _sample_spec(family)
    limit = int(spec.get('max_n', 4096))
    if limit <= 32:
        pytest.skip('该题种子的 max_n 已在最小档附近')
    # The ladder stops at the doubling cap (4096), so a smaller max_n has to be
    # expressed below that cap to observe the shrink.
    target = min(limit // 4, 1024)
    full = probe.ladder(family, SEED, spec)
    reduced = probe.ladder(family, SEED, {**spec, 'max_n': target})
    assert full[-1].n <= limit
    assert reduced
    assert all(rung.n <= target for rung in reduced)
    assert reduced[-1].n < full[-1].n


def _reference_source(code: str) -> str:
    for solution in BANK[code]:
        if solution.get('language') == 'Python':
            return solution['content']
    raise AssertionError(f'{code} 没有 Python 参考解')


@pytest.mark.parametrize('code', REFERENCE_CASES)
def test_reference_solution_accepts_smallest_rung(code, judge_work_root):
    family, spec = PROFILES[code]
    rungs = probe.ladder(family, SEED, spec)
    assert len(rungs) >= 3
    trace = python_adapter.collect(_reference_source(code), [rungs[0]],
                                   deadline=time.monotonic() + 10, seed=SEED)
    assert trace.points, trace.notes
    point = trace.points[0]
    assert point.verdict == 'OK', point.detail
    assert point.work > 0
