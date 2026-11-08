"""Closed-form growth fitting over exact work counts.

The old implementation fitted wall-clock milliseconds. The failure that
motivated this rebuild was structural: on a doubling ladder ``n`` and
``n log n`` are almost collinear in time, the R^2 difference was about 0.001,
and 40 noisy samples in the experiment lost the distinction 13 times. Here the
input is an integer count of executed operations. The two bases differ by a
factor of ``log2(n)`` — at least 5x on the smallest ladder the platform uses —
and the residual of the correct model is effectively zero, so the choice is no
longer decided by a margin that noise can swamp.

One thing that has to be modelled explicitly is the lower-order term. A count
curve is never exactly ``a*f(n)``: reading the input leaves a little linear
residue, a Python loop over the data adds another linear term, and a program that
sorts and then scans is genuinely ``a*n log n + b*n``. Fitting only ``a*f(n)+c``
then lets the lower-order term decide between neighbouring classes (the first
experiment reported five ``n log n`` programs as ``O(n)`` for exactly this
reason). So each class above ``O(n)`` is fitted with its natural lower-order
basis as well, and the classes are compared with AIC — residual plus a penalty
for the extra parameter — instead of raw residual. That keeps the extra term from
buying a higher class for free.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .classes import CLASS_RANK, SPACE_CLASSES, TIME_CLASSES, GROWTH_FUNCTIONS

# A candidate class must explain at least this share of the variance before it
# may be published at all.
MINIMUM_R2 = 0.90
# AIC differences between the winner and the runner-up. 10 is the usual "strong
# evidence" threshold; 4 is "considerable". Below that the ladder cannot tell the
# two apart and the report says so.
CLEAR_AIC = 10.0
WORKABLE_AIC = 4.0
# Space increments below this are indistinguishable from allocator bookkeeping.
SPACE_NOISE_BYTES = 16 * 1024

# A candidate is rejected when its leading term explains less than this share of
# the work at the largest rung. Without the floor, ``O(n log n)`` fitted with a
# linear lower-order term can mimic a purely linear series with a vanishingly
# small leading coefficient, and every linear program would lose its confidence
# to a model that is really just ``b*n + c`` under another name.
MINIMUM_LEAD_SHARE = 0.20

# The lower-order term that goes with each class when the model has enough rungs
# to fit three parameters. Classes up to ``O(n)`` only get a constant: adding a
# linear term to a constant or logarithmic model would silently make it linear.
LOWER_TERMS = {
    'O(n log n)': 'O(n)',
    'O(n^2)': 'O(n)',
    'O(n^2 log n)': 'O(n^2)',
    'O(n^3)': 'O(n^2)',
    'O(2^n)': 'O(n^2)',
    'O(n!)': 'O(n^2)',
}


@dataclass
class Candidate:
    name: str
    sse: float
    r2: float
    aic: float
    parameters: int
    coefficient: float
    lower: float = 0.0
    offset: float = 0.0


@dataclass
class ClassFit:
    time_class: str
    confidence: str
    best: Candidate | None = None
    candidates: list[Candidate] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    order: tuple[str, ...] = TIME_CLASSES

    @property
    def margin(self) -> float | None:
        if len(self.candidates) < 2:
            return None
        best_sse = max(self.candidates[0].sse, 1e-9)
        return self.candidates[1].sse / best_sse

    @property
    def delta_aic(self) -> float | None:
        if len(self.candidates) < 2:
            return None
        return self.candidates[1].aic - self.candidates[0].aic

    def to_payload(self) -> dict:
        return {
            'class': self.time_class,
            'confidence': self.confidence,
            'margin': None if self.margin is None else round(self.margin, 3),
            'delta_aic': None if self.delta_aic is None else round(self.delta_aic, 3),
            'best': None if self.best is None else {
                'class': self.best.name, 'r2': round(self.best.r2, 6),
                'sse': round(self.best.sse, 4), 'aic': round(self.best.aic, 3),
                'parameters': self.best.parameters,
                'coefficient': self.best.coefficient, 'offset': self.best.offset,
                'lower': self.best.lower,
            },
            'candidates': [
                {'class': row.name, 'r2': round(row.r2, 6), 'sse': round(row.sse, 4),
                 'aic': round(row.aic, 3), 'parameters': row.parameters}
                for row in self.candidates[:4]
            ],
            'notes': list(self.notes),
        }


def _normalize(values: list[float]) -> tuple[list[float], float] | None:
    """Scale a basis by its largest value so squaring cannot overflow."""
    scale = max(abs(value) for value in values)
    if scale <= 0 or not math.isfinite(scale):
        return None
    return [value / scale for value in values], scale


def _fit_two(values: list[float], counts: list[float]) -> tuple[float, float] | None:
    """Least squares for ``count = a * value + c`` with ``a > 0``.

    The offset is allowed to be negative. Counts are work units after subtracting
    the input-parsing baseline, so a negative offset simply means the baseline
    over-estimated the lower-order term; clamping it to zero would bend a
    perfectly affine logarithm into a line and mis-name slow-growing programs.
    """
    normalized = _normalize(values)
    if normalized is None:
        return None
    scaled, scale = normalized
    size = len(scaled)
    mean_v = sum(scaled) / size
    mean_c = sum(counts) / size
    denominator = sum((value - mean_v) ** 2 for value in scaled)
    if denominator <= 1e-18:
        return (mean_c, 0.0) if mean_c > 0 else None
    a = sum((value - mean_v) * (count - mean_c)
            for value, count in zip(scaled, counts)) / denominator
    if a <= 0:
        return None
    c = mean_c - a * mean_v
    return a / scale, c


def _solve(matrix: list[list[float]], rhs: list[float]) -> list[float] | None:
    """Gaussian elimination with partial pivoting for a small dense system."""
    size = len(rhs)
    rows = [list(matrix[index]) + [rhs[index]] for index in range(size)]
    for column in range(size):
        pivot = max(range(column, size), key=lambda row: abs(rows[row][column]))
        if abs(rows[pivot][column]) <= 1e-12:
            return None
        rows[column], rows[pivot] = rows[pivot], rows[column]
        divisor = rows[column][column]
        rows[column] = [value / divisor for value in rows[column]]
        for other in range(size):
            if other == column:
                continue
            factor = rows[other][column]
            if factor:
                rows[other] = [value - factor * base
                               for value, base in zip(rows[other], rows[column])]
    return [rows[index][-1] for index in range(size)]


def _fit_three(values: list[float], lower: list[float],
               counts: list[float]) -> tuple[float, float, float] | None:
    """Least squares for ``count = a * value + b * lower + c`` with ``a > 0``."""
    first = _normalize(values)
    second = _normalize(lower)
    if first is None or second is None:
        return None
    f_scaled, f_scale = first
    g_scaled, g_scale = second
    ones = [1.0] * len(counts)
    columns = (f_scaled, g_scaled, ones)
    matrix = [[sum(left * right for left, right in zip(columns[i], columns[j]))
               for j in range(3)] for i in range(3)]
    rhs = [sum(column * count for column, count in zip(columns[row], counts))
           for row in range(3)]
    solution = _solve(matrix, rhs)
    if solution is None:
        return None
    a, b, c = solution
    if a <= 0:
        return None
    return a / f_scale, b / g_scale, c


def _leading_term_matters(coefficient: float, basis: float, prediction: float) -> bool:
    """Reject a fit whose named class contributes almost nothing at the top rung."""
    if prediction == 0:
        return False
    share = abs(coefficient * basis) / abs(prediction)
    return share >= MINIMUM_LEAD_SHARE


def _candidate(name: str, counts: list[float], sizes: list[int],
               total_variance: float, rung_count: int) -> Candidate | None:
    function = GROWTH_FUNCTIONS.get(name)
    if function is None:
        return None
    values = [float(function(n)) for n in sizes]
    if not all(math.isfinite(value) for value in values):
        return None
    mean = sum(counts) / len(counts)
    if name == 'O(1)':
        sse = total_variance
        parameters = 1
        coefficient, lower, offset = mean, 0.0, 0.0
    else:
        lower_name = LOWER_TERMS.get(name) if rung_count >= 5 else None
        fitted = None
        if lower_name is not None:
            lower_values = [float(GROWTH_FUNCTIONS[lower_name](n)) for n in sizes]
            if all(math.isfinite(value) for value in lower_values):
                fitted = _fit_three(values, lower_values, counts)
                if fitted is not None:
                    a, b, c = fitted
                    predictions = [a * value + b * low + c
                                   for value, low in zip(values, lower_values)]
                    sse = sum((count - predicted) ** 2
                              for count, predicted in zip(counts, predictions))
                    parameters = 3
                    coefficient, lower, offset = a, b, c
                    if not _leading_term_matters(a, values[-1], predictions[-1]):
                        fitted = None
                        lower_name = None
        if fitted is None:
            affine = _fit_two(values, counts)
            if affine is None:
                return None
            a, c = affine
            predictions = [a * value + c for value in values]
            if not _leading_term_matters(a, values[-1], predictions[-1]):
                return None
            sse = sum((count - predicted) ** 2
                      for count, predicted in zip(counts, predictions))
            parameters = 2
            coefficient, lower, offset = a, 0.0, c
    r2 = 0.0 if total_variance <= 1e-12 else 1.0 - sse / total_variance
    aic = rung_count * math.log(max(sse / rung_count, 1e-12)) + 2 * parameters
    return Candidate(name, sse, r2, aic, parameters, coefficient, lower, offset)


def fit_growth(points: list[tuple[int, float]], classes: tuple[str, ...] = TIME_CLASSES,
               *, minimum_points: int = 3) -> ClassFit:
    """Fit a growth class to ``(n, work)`` pairs.

    Candidates are ranked by AIC: the higher classes get a lower-order basis, so
    ranking by raw residual would let the extra parameter buy a class. Confidence
    comes from the AIC gap to the runner-up, not from an absolute R^2.
    """
    usable: dict[int, float] = {}
    for n, work in points:
        if n <= 0 or work <= 0:
            continue
        try:
            value = float(work)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(value):
            continue
        usable[int(n)] = value
    ordered = sorted(usable.items())
    sizes = [n for n, _ in ordered]
    counts = [work for _, work in ordered]
    if len(ordered) < minimum_points:
        return ClassFit('UNKNOWN', 'LOW', notes=[
            f'有效档位只有 {len(ordered)} 个，少于 {minimum_points} 个，无法估计增长'])
    mean = sum(counts) / len(counts)
    variance = sum((count - mean) ** 2 for count in counts)
    if variance <= 1e-12:
        constant = Candidate('O(1)', 0.0, 1.0, 0.0, 1, mean)
        return ClassFit('O(1)', 'HIGH', best=constant, candidates=[constant],
                        notes=['工作量在全部档位上相同'])
    candidates: list[Candidate] = []
    for name in classes:
        candidate = _candidate(name, counts, sizes, variance, len(ordered))
        if candidate is not None:
            candidates.append(candidate)
    if not candidates:
        return ClassFit('UNKNOWN', 'LOW', notes=['所有候选类别都无法拟合计数序列'])
    candidates.sort(key=lambda row: (row.aic, CLASS_RANK.get(row.name, 99)))
    best = candidates[0]
    runner_up = candidates[1] if len(candidates) > 1 else None
    notes: list[str] = []
    if best.r2 < MINIMUM_R2:
        notes.append(f'最优类别 {best.name} 只能解释 {best.r2:.3f} 的计数变化，结论只能作为参考')
        return ClassFit('UNKNOWN', 'LOW', best=best, candidates=candidates, notes=notes)
    delta = None if runner_up is None else runner_up.aic - best.aic
    confidence = 'LOW'
    if delta is not None and len(ordered) >= 5 and delta >= CLEAR_AIC:
        confidence = 'HIGH'
    elif delta is not None and len(ordered) >= 4 and delta >= WORKABLE_AIC:
        confidence = 'MEDIUM'
    if runner_up is None:
        notes.append('其余类别的主项在最大档位占比过低，无法解释这份计数序列')
        if len(ordered) >= 5 and best.r2 >= 0.99:
            confidence = 'HIGH'
        elif len(ordered) >= 4:
            confidence = 'MEDIUM'
        else:
            confidence = 'LOW'
    elif delta is not None and delta < WORKABLE_AIC:
        notes.append(f'{best.name} 与 {runner_up.name} 的拟合优度相差很小'
                     f'（AIC 差 {delta:.1f}），档位数不足以区分两者')
    return ClassFit(best.name, confidence, best=best, candidates=candidates, notes=notes)


def fit_space(points: list[tuple[int, int | None]]) -> ClassFit:
    """Fit the growth of peak allocation to a space class.

    The smallest observed peak is treated as the baseline (interpreter, runtime,
    loaded libraries) and subtracted. For C++ the underlying numbers are exact
    allocation counters; for Python they are ``tracemalloc`` peaks, which are
    deterministic for a deterministic program.
    """
    usable = [(n, value) for n, value in points if n > 0 and value is not None and value > 0]
    if len(usable) < 3:
        return ClassFit('UNKNOWN', 'LOW', order=SPACE_CLASSES,
                        notes=['可用内存档位不足 3 个，无法判断空间增长'])
    baseline = min(value for _, value in usable)
    increments = [(n, max(0, value - baseline)) for n, value in usable]
    largest = max(value for _, value in increments)
    if largest < SPACE_NOISE_BYTES:
        constant = Candidate('O(1)', 0.0, 1.0, 0.0, 1, float(baseline))
        return ClassFit('O(1)', 'HIGH', best=constant, candidates=[constant],
                        order=SPACE_CLASSES, notes=['峰值分配在各档位上基本不变'])
    fit = fit_growth([(n, value) for n, value in increments if value > 0],
                     classes=SPACE_CLASSES)
    fit.order = SPACE_CLASSES
    if fit.time_class == 'UNKNOWN':
        fit.notes.append('峰值分配的增长形态无法匹配任何空间类别')
    return fit


def fit_depth(points: list[tuple[int, int]]) -> ClassFit:
    """Fit how the maximum recursion depth grows, as a stack-space lower bound."""
    usable = [(n, depth) for n, depth in points if n > 0 and depth > 0]
    if len(usable) < 3:
        return ClassFit('UNKNOWN', 'LOW', order=('O(1)', 'O(log n)', 'O(n)'))
    if max(depth for _, depth in usable) == min(depth for _, depth in usable):
        return ClassFit('O(1)', 'MEDIUM', order=('O(1)', 'O(log n)', 'O(n)'))
    fit = fit_growth(usable, classes=('O(1)', 'O(log n)', 'O(n)'))
    fit.order = ('O(1)', 'O(log n)', 'O(n)')
    return fit
