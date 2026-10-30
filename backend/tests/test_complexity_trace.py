"""Unit tests for the trace-based complexity engine.

The inference layer is pure: it is tested against synthetic count series and
synthetic call trees, so a regression here does not need a subprocess. The last
group runs the real Python tracer on small ladders to prove the collected counts
actually drive the classification.
"""
import math

import pytest

from app.analysis.trace import collect, infer, schema
from app.analysis.trace.fit import fit_depth, fit_growth, fit_space
from app.analysis.trace.recurrence import infer_recurrence, solve_recurrence

SIZES = (32, 64, 128, 256, 512, 1024)


def _series(shape, *, sizes=SIZES, coefficient=3.5, lower=0.7, constant=11.0):
    function = {
        'O(1)': lambda n: 1.0,
        'O(log n)': lambda n: math.log2(n),
        'O(n)': lambda n: float(n),
        'O(n log n)': lambda n: n * math.log2(n),
        'O(n^2)': lambda n: float(n) ** 2,
        'O(n^2 log n)': lambda n: (n ** 2) * math.log2(n),
        'O(n^3)': lambda n: float(n) ** 3,
        'O(2^n)': lambda n: 2.0 ** n,
        'O(n!)': lambda n: float(math.factorial(n)),
    }[shape]
    if shape == 'O(1)':
        return [(n, coefficient + constant) for n in sizes]
    return [(n, coefficient * function(n) + lower * n + constant) for n in sizes]


@pytest.mark.parametrize('shape', ['O(1)', 'O(log n)', 'O(n)', 'O(n log n)', 'O(n^2)',
                                   'O(n^2 log n)', 'O(n^3)'])
def test_fit_recovers_every_polynomial_class_from_exact_counts(shape):
    # A log or constant program cannot also carry a linear lower-order term: that
    # term would be the dominant work and the correct class would be O(n).
    lower = 0.0 if shape in ('O(1)', 'O(log n)') else 0.7
    fit = fit_growth(_series(shape, lower=lower))
    assert fit.time_class == shape, (shape, fit.time_class, fit.candidates[:2])
    assert fit.confidence == 'HIGH'


@pytest.mark.parametrize('shape,sizes', [
    ('O(2^n)', (5, 8, 11, 14, 17, 20)),
    ('O(n!)', (5, 6, 7, 8, 9, 10)),
])
def test_fit_separates_exponential_and_factorial(shape, sizes):
    fit = fit_growth(_series(shape, sizes=sizes, lower=0.0, constant=3.0))
    assert fit.time_class == shape, (shape, fit.time_class, fit.candidates[:2])


def test_fit_prefers_n_log_n_over_n_even_with_a_linear_lower_order_term():
    """The defect that motivated the rebuild: n and n log n must be separable."""
    fit = fit_growth(_series('O(n log n)', lower=2.0))
    assert fit.time_class == 'O(n log n)'
    runner_up = fit.candidates[1]
    assert runner_up.name in ('O(n)', 'O(n^2 log n)', 'O(n^2)')


def test_fit_needs_three_points_and_says_so():
    fit = fit_growth([(64, 100.0), (128, 200.0)])
    assert fit.time_class == 'UNKNOWN' and fit.confidence == 'LOW'
    assert '少于 3 个' in ' '.join(fit.notes)


def test_fit_does_not_invent_a_class_from_noise():
    noisy = [(32, 17.0), (64, 3.0), (128, 400.0), (256, 12.0), (512, 900.0), (1024, 4.0)]
    fit = fit_growth(noisy)
    assert fit.confidence in ('LOW', 'MEDIUM') or fit.time_class == 'UNKNOWN'


def test_constant_work_is_reported_as_constant_not_as_a_log():
    fit = fit_growth([(n, 500.0) for n in SIZES])
    assert fit.time_class == 'O(1)' and fit.confidence == 'HIGH'


def test_space_fit_follows_peak_increments():
    linear = [(n, 1_000_000 + 800 * n) for n in SIZES]
    assert fit_space(linear).time_class == 'O(n)'
    flat = [(n, 1_000_000 + 64) for n in SIZES]
    assert fit_space(flat).time_class == 'O(1)'
    square = [(n, 1_000_000 + 8 * n * n) for n in SIZES]
    assert fit_space(square).time_class == 'O(n^2)'


def test_depth_fit_follows_recursion_depth():
    assert fit_depth([(n, 3 + math.log2(n)) for n in SIZES]).time_class == 'O(log n)'
    assert fit_depth([(n, n // 2) for n in SIZES]).time_class == 'O(n)'


@pytest.mark.parametrize('a,ratio,step,shrink,frame,expected,method', [
    (2, 0.5, None, 'HALVING', 'O(n)', 'O(n log n)', 'MASTER'),
    (1, 0.5, None, 'HALVING', 'O(1)', 'O(log n)', 'MASTER'),
    (1, 0.5, None, 'HALVING', 'O(n)', 'O(n)', 'MASTER'),
    (2, 0.5, None, 'HALVING', 'O(1)', 'O(n)', 'MASTER'),
    (3, 0.5, None, 'HALVING', 'O(n)', 'O(n^2)', 'MASTER'),      # Karatsuba: bounded above
    (1, None, 1, 'DECREMENT', 'O(1)', 'O(n)', 'SUMMATION'),
    (1, None, 1, 'DECREMENT', 'O(n)', 'O(n^2)', 'SUMMATION'),
    (2, None, 1, 'DECREMENT', 'O(1)', 'O(2^n)', 'EXPONENTIAL'),
    (2, None, 1, 'DECREMENT', 'O(n)', 'O(2^n)', 'EXPONENTIAL'),
])
def test_recurrence_solver_matches_the_textbook_cases(a, ratio, step, shrink, frame,
                                                      expected, method):
    solved = solve_recurrence(a, ratio, step, shrink, frame)
    assert solved['class'] == expected, solved
    assert solved['method'] == method
    assert solved['expression'].startswith('T(n) = ')


def test_recurrence_solver_bounds_an_unnamed_growth_with_a_note():
    solved = solve_recurrence(2, 0.5, None, 'HALVING', 'O(n log n)')
    assert solved['class'] == 'O(n^2)'
    assert solved['solution'] == 'Θ(n log^2 n)'
    assert solved['notes']


def _mergesort_points():
    sizes = (64, 128, 256, 512, 1024)
    points = []
    for n in sizes:
        work = 2.2 * n * math.log2(n) + 0.6 * n
        function = schema.FunctionTrace(name='merge_sort')
        for size in (n, n // 2, n // 4, n // 8):
            if size > 4:
                function.add_sample(schema.FrameSample(
                    args=(size,), cost=0.6 * size + 2,
                    children=((size // 2,), (size - size // 2,))))
        points.append(schema.TracePoint(n=n, work=work, line_events=int(work),
                                        functions={'merge_sort': function}))
    return points


def test_recurrence_is_read_from_a_mergesort_call_tree():
    recurrence = infer_recurrence(_mergesort_points())
    assert recurrence is not None
    assert recurrence.function == 'merge_sort'
    assert recurrence.branching == 2
    assert recurrence.shrink == 'HALVING'
    assert recurrence.frame_class == 'O(n)'
    assert recurrence.time_class == 'O(n log n)'
    assert recurrence.expression == 'T(n) = 2·T(n/2) + O(n)'


def _hanoi_points():
    sizes = (6, 9, 12, 15, 18)
    points = []
    for n in sizes:
        work = 2.0 ** n
        function = schema.FunctionTrace(name='hanoi')
        for size in range(6, n + 1):
            function.add_sample(schema.FrameSample(
                args=(size,), cost=1.0,
                children=((size - 1,), (size - 1,)) if size > 1 else ()))
        points.append(schema.TracePoint(n=n, work=work, functions={'hanoi': function}))
    return points


def test_recurrence_is_read_from_a_decrementing_recursion():
    recurrence = infer_recurrence(_hanoi_points())
    assert recurrence is not None
    assert recurrence.shrink == 'DECREMENT'
    assert recurrence.time_class == 'O(2^n)'
    assert 'T(n-1)' in recurrence.expression


def test_data_dependent_recursion_refuses_to_invent_a_recurrence():
    sizes = (64, 128, 256, 512, 1024)
    points = []
    for n in sizes:
        work = 2.0 * n * math.log2(n)
        function = schema.FunctionTrace(name='quicksort')
        for size in (n, n // 2, n // 3):
            if size > 4:
                function.add_sample(schema.FrameSample(
                    args=(size,), cost=float(size),
                    children=((size // 7,), (size - size // 7 - 1,))))
        points.append(schema.TracePoint(n=n, work=work, functions={'quicksort': function}))
    recurrence = infer_recurrence(points)
    assert recurrence is not None
    assert recurrence.shrink == 'DATA_DEPENDENT'
    assert recurrence.time_class is None
    assert any('没有固定的缩放关系' in note for note in recurrence.notes)


def _ladder(points, **overrides):
    return schema.LadderTrace(language='python3', adapter='python-monitoring-v1',
                              work_unit='LINE+JUMP+库函数折算', points=points,
                              stop_reason=overrides.pop('stop_reason', 'OK'), **overrides)


def test_input_parsing_baseline_is_subtracted_before_fitting():
    """A program that reads n tokens and does constant work is O(1), not O(n)."""
    points = [schema.TracePoint(n=n, work=10 * n + 40, baseline_work=10 * n,
                                line_events=5, lines={'main:1': 1})
              for n in SIZES]
    conclusion = infer.infer(_ladder(points))
    assert conclusion.time.time_class == 'O(1)'
    assert any('输入解析基准' in text for text in conclusion.limitations)


def test_baseline_subtraction_keeps_the_algorithm_class():
    points = [schema.TracePoint(n=n, work=n * math.log2(n) + 10 * n,
                                baseline_work=10 * n,
                                lines={'merge:7': int(n * math.log2(n))})
              for n in SIZES]
    conclusion = infer.infer(_ladder(points))
    assert conclusion.time.time_class == 'O(n log n)'
    assert any(row['kind'] == 'LINE' for row in conclusion.evidence)


def test_work_below_the_baseline_falls_back_to_the_total_growth():
    """When the algorithm never outworks the reader, the honest answer is the
    growth of the total program, with the reading included in the explanation."""
    points = [schema.TracePoint(n=n, work=10 * n - 5, baseline_work=10 * n + 100,
                                lines={'main:1': 1})
              for n in SIZES]
    conclusion = infer.infer(_ladder(points))
    assert conclusion.time.time_class == 'O(n)'
    assert any('输入解析基准' in text for text in conclusion.limitations)


def test_program_whose_own_work_is_constant_is_constant():
    points = [schema.TracePoint(n=n, work=40.0, baseline_work=10 * n,
                                lines={'main:1': 1})
              for n in SIZES]
    conclusion = infer.infer(_ladder(points))
    assert conclusion.time.time_class == 'O(1)'
    assert any('常数' in text for text in conclusion.limitations)


def test_unknown_library_calls_and_non_determinism_are_reported():
    points = [schema.TracePoint(n=n, work=2.0 * n * math.log2(n) + 5,
                                opaque_calls={'weird': 1},
                                lines={'merge:7': int(n)})
              for n in SIZES]
    ladder = _ladder(points, deterministic=False, repeat_delta=0.4)
    conclusion = infer.infer(ladder, language_label='Python 3')
    assert conclusion.time.time_class == 'O(n log n)'
    assert any('计数不一致' in text for text in conclusion.limitations)
    assert any('Python 3' in text for text in conclusion.time.notes)


def test_schema_payload_round_trips_the_trace_fields():
    point = schema.TracePoint(n=64, work=123.0, baseline_work=12.0, peak_bytes=4096,
                              max_depth=5, opaque_calls={'x': 2},
                              lines={'f:3': 9})
    payload = point.to_payload()
    assert payload['baseline_work'] == 12.0
    assert payload['peak_bytes'] == 4096
    assert payload['lines'] == {'f:3': 9}
    ladder = _ladder([point], deterministic=True)
    assert ladder.to_payload()['deterministic'] is True


def test_language_support_is_explicit():
    assert collect.supports_language('python3') is True
    assert collect.supports_language('java') is False
    assert collect.supports_language('brainfuck') is False


# ------------------------------------------------------------ real execution


def _trace_source(source, family, spec, *, seed=11):
    return collect.collect(source, 'python3', family, spec, seed=seed, budget_ms=15_000)


MERGE_SORT = '''
import sys
def merge_sort(a):
    if len(a) <= 1:
        return a
    mid = len(a) // 2
    left = merge_sort(a[:mid])
    right = merge_sort(a[mid:])
    return merge(left, right)
def merge(left, right):
    out = []
    i = j = 0
    while i < len(left) and j < len(right):
        if left[i] <= right[j]:
            out.append(left[i]); i += 1
        else:
            out.append(right[j]); j += 1
    out.extend(left[i:]); out.extend(right[j:])
    return out
data = list(map(int, sys.stdin.buffer.read().split()))
merge_sort(data)
'''

READ_AND_PRINT = '''
import sys
data = list(map(int, sys.stdin.buffer.read().split()))
print(data[0] if data else 0)
'''

BUBBLE = '''
import sys
data = list(map(int, sys.stdin.buffer.read().split()))
n = len(data)
for i in range(n):
    for j in range(n - 1 - i):
        if data[j] > data[j + 1]:
            data[j], data[j + 1] = data[j + 1], data[j]
'''


def test_python_tracer_classifies_a_mergesort_from_real_counts():
    ladder = _trace_source(MERGE_SORT, 'INT_ARRAY', {'max_n': 1024})
    assert len(ladder.ok_points) >= 4
    assert ladder.deterministic is True
    conclusion = infer.infer(ladder, language_label='Python 3')
    assert conclusion.time.time_class == 'O(n log n)'
    assert conclusion.time.method == 'RECURRENCE'
    assert conclusion.time.recurrence is not None
    assert conclusion.time.recurrence.expression == 'T(n) = 2·T(n/2) + O(n)'
    first, last = ladder.ok_points[0], ladder.ok_points[-1]
    assert last.work > first.work
    assert last.baseline_work > 0, 'the input-parsing baseline must be measured'


def test_python_tracer_separates_linear_work_from_input_reading():
    """Reading n tokens is linear for every program; the algorithm is not."""
    ladder = _trace_source(READ_AND_PRINT, 'INT_ARRAY', {'max_n': 2048})
    conclusion = infer.infer(ladder, language_label='Python 3')
    assert conclusion.time.time_class == 'O(1)'
    bubble = _trace_source(BUBBLE, 'INT_ARRAY', {'max_n': 512})
    assert infer.infer(bubble).time.time_class == 'O(n^2)'


def test_python_tracer_is_repeatable():
    first = _trace_source(MERGE_SORT, 'INT_ARRAY', {'max_n': 512}, seed=5)
    second = _trace_source(MERGE_SORT, 'INT_ARRAY', {'max_n': 512}, seed=5)
    assert [p.n for p in first.ok_points] == [p.n for p in second.ok_points]
    assert [p.work for p in first.ok_points] == [p.work for p in second.ok_points]
