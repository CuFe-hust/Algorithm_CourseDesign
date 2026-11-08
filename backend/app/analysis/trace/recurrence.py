"""Recurrence extraction and solving from a call trace.

For a recursive program the trace contains the call tree: which function called
which, with what argument sizes, and how much work each frame did outside its
recursive children. That is enough to read a recurrence off the program without
looking at its syntax:

* ``a`` — how many recursive calls a frame makes,
* the shrink relation — child argument over parent argument (halving), a fixed
  decrease (``n-1``) or a constant argument,
* ``f(n)`` — the frame's non-recursive work as a function of its argument.

The solver then applies the Master theorem for halving recurrences, a summation
rule for decreasing recurrences and the exponential rule for branching
decreases. It returns both the recurrence and a closed form; the caller checks
the closed form against the measured total before publishing it, so a
mis-detected structure is reported as "closed form only" instead of being
presented as an explanation.

One weakness is explicit: a recursion whose argument is split by a data value
(quicksort, randomised select) does not have a fixed ``a f(n/b)`` shape. The
detector marks those ``DATA_DEPENDENT`` and refuses to invent a recurrence; the
report falls back to the measured growth and says so.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field

from .classes import CLASS_RANK, describe_exponent
from .fit import fit_growth
from .schema import FrameSample, TracePoint

# The frame work vocabulary. Anything above a square in one frame is already
# the dominant term and does not need a recurrence to name it.
FRAME_CLASSES = ('O(1)', 'O(log n)', 'O(n)', 'O(n log n)', 'O(n^2)')

DECREMENT_CLASSES = {
    'O(1)': 'O(n)',
    'O(log n)': 'O(n log n)',
    'O(n)': 'O(n^2)',
    'O(n log n)': 'O(n^2 log n)',
    'O(n^2)': 'O(n^3)',
}


@dataclass
class Recurrence:
    function: str
    branching: int
    shrink: str
    frame_class: str
    expression: str | None = None
    solution: str | None = None
    time_class: str | None = None
    method: str = 'NONE'
    ratio: float | None = None
    step: float | None = None
    frame_confidence: str = 'LOW'
    share: float = 0.0
    notes: list[str] = field(default_factory=list)

    def to_payload(self) -> dict:
        return {
            'function': self.function,
            'branching': self.branching,
            'shrink': self.shrink,
            'frame_class': self.frame_class,
            'expression': self.expression,
            'solution': self.solution,
            'class': self.time_class,
            'method': self.method,
            'ratio': None if self.ratio is None else round(self.ratio, 4),
            'step': None if self.step is None else round(self.step, 4),
            'frame_confidence': self.frame_confidence,
            'share': round(self.share, 3),
            'notes': list(self.notes),
        }


def infer_recurrence(points: list[TracePoint]) -> Recurrence | None:
    """Read a recurrence from the function samples of a ladder.

    Returns ``None`` when no function shows self-recursion with usable
    argument samples (iterative programs, native languages without argument
    capture, or traces that were thinned too aggressively).
    """
    usable = [point for point in points if point.ok and point.functions]
    if len(usable) < 3:
        return None
    candidates: list[Recurrence] = []
    names = {name for point in usable for name in point.functions}
    for name in names:
        samples_by_point = [(point.n, point.functions[name]) for point in usable
                            if name in point.functions]
        if len(samples_by_point) < 3:
            continue
        recurrence = _recurrence_for(name, samples_by_point, usable)
        if recurrence is None:
            continue
        candidates.append(recurrence)
    if not candidates:
        return None
    # A recursive helper can show a simpler recurrence than the function the
    # module actually starts from; the one that accounts for most of the work is
    # the structure worth reporting.
    return max(candidates, key=lambda item: (item.share, CLASS_RANK.get(item.time_class or '', -1)))


def _recurrence_for(name: str, samples_by_point, points: list[TracePoint]) -> Recurrence | None:
    samples: list[FrameSample] = []
    for _, function in samples_by_point:
        samples.extend(function.samples)
    recursive = [sample for sample in samples if sample.children]
    if len(recursive) < 6:
        return None
    branching = int(statistics.median(len(sample.children) for sample in recursive))
    if branching < 1:
        return None
    shrink, ratio, step = _detect_shrink(recursive)
    frame_points = _frame_cost_points(recursive)
    if len(frame_points) < 3:
        return None
    frame_fit = fit_growth(frame_points, classes=FRAME_CLASSES)
    frame_class = frame_fit.time_class
    if frame_class == 'UNKNOWN':
        frame_class = 'O(1)'
        frame_notes = ['每帧非递归工作量的增长形态无法识别，按常数处理']
    else:
        frame_notes = list(frame_fit.notes)
    share = _work_share(name, samples_by_point, points)
    recurrence = Recurrence(function=name, branching=branching, shrink=shrink,
                            frame_class=frame_class, ratio=ratio, step=step,
                            frame_confidence=frame_fit.confidence, share=share)
    recurrence.notes.extend(frame_notes)
    if shrink == 'DATA_DEPENDENT':
        recurrence.notes.append('递归参数按数据切分，没有固定的缩放关系，未还原递推式')
        return recurrence
    solved = solve_recurrence(branching, ratio, step, shrink, frame_class)
    recurrence.expression = solved['expression']
    recurrence.solution = solved['solution']
    recurrence.time_class = solved['class']
    recurrence.method = solved['method']
    recurrence.notes.extend(solved['notes'])
    return recurrence


def _detect_shrink(samples: list[FrameSample]) -> tuple[str, float | None, float | None]:
    """Classify how a recursive call shrinks its first argument."""
    ratios: list[float] = []
    differences: list[float] = []
    constant_children = 0
    total_children = 0
    for sample in samples:
        parent = sample.args[0] if sample.args else 0
        if parent <= 4:
            continue
        for child_args in sample.children:
            child = child_args[0] if child_args else 0
            total_children += 1
            if child <= 0:
                continue
            ratios.append(child / parent)
            differences.append(parent - child)
            if child <= 4:
                constant_children += 1
    if len(ratios) < 6:
        return 'DATA_DEPENDENT', None, None
    if constant_children == total_children and total_children:
        return 'CONSTANT', None, None
    positive_diffs = [difference for difference in differences if difference > 0]
    parents = [sample.args[0] for sample in samples if sample.args and sample.args[0] > 4]
    median_parent = statistics.median(parents) if parents else 1.0
    # A fixed decrease stays small compared with the argument it is applied to:
    # n-1, n-2, n-10 all qualify. It is checked before the ratio test because a
    # decrease looks like a shrinking ratio at small arguments (fib's (n-1)/n is
    # 0.8 at n=5) and would otherwise be read as a division.
    if positive_diffs and max(positive_diffs) <= max(8.0, 0.25 * median_parent):
        return 'DECREMENT', None, min(positive_diffs)
    median_ratio = statistics.median(ratios)
    spread = _coefficient_of_variation(ratios)
    if 0.0 < median_ratio < 0.95 and spread <= 0.18:
        return 'HALVING', median_ratio, None
    return 'DATA_DEPENDENT', median_ratio, None


def _coefficient_of_variation(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = statistics.fmean(values)
    if mean <= 0:
        return float('inf')
    return statistics.pstdev(values) / mean


def _frame_cost_points(samples: list[FrameSample]) -> list[tuple[int, float]]:
    """``(argument size, non-recursive work in the frame)`` pairs.

    Calls on tiny arguments are left out: base cases have a fixed setup cost and
    would flatten the fit of the recursive frame's own work.
    """
    points: list[tuple[int, float]] = []
    for sample in samples:
        size = sample.args[0] if sample.args else 0
        if size > 4 and sample.cost > 0:
            points.append((int(size), float(sample.cost)))
    return points


def _work_share(name: str, samples_by_point, points: list[TracePoint]) -> float:
    total_work = sum(point.work for point in points)
    if total_work <= 0:
        return 0.0
    estimated = 0.0
    for _, function in samples_by_point:
        if not function.samples:
            continue
        mean_cost = statistics.fmean(sample.cost for sample in function.samples)
        estimated += function.calls * mean_cost
    return max(0.0, min(1.0, estimated / total_work))


def solve_recurrence(branching: int, ratio: float | None, step: float | None,
                     shrink: str, frame_class: str) -> dict:
    """Solve ``T(n) = a T(n/b) + f(n)`` (or the decreasing variant).

    Returns ``{'expression', 'solution', 'class', 'method', 'notes'}``; ``class``
    is ``None`` when the derived growth has no name in the platform vocabulary
    (for example ``3^n`` or ``log^2 n``); the solution string still states it and
    a note names the nearest published bound.
    """
    notes: list[str] = []
    if shrink == 'HALVING':
        b = 1.0 / ratio if ratio else 2.0
        expression = _recurrence_expression(branching, f'n/{_format_number(b)}', frame_class)
        return _solve_master(branching, b, frame_class, expression, notes)
    if shrink == 'DECREMENT':
        expression = _recurrence_expression(branching, f'n-{_format_number(step or 1)}',
                                            frame_class)
        if step is not None and abs(step - 1.0) > 1e-9:
            notes.append(f'子调用规模按 n-{_format_number(step)} 递减（部分子问题减得更多），'
                         '递推式按每层减 1 保守估计，给出的是上界')
        if branching == 1:
            time_class = DECREMENT_CLASSES.get(frame_class)
            if time_class is None:
                notes.append(f'递减递归的每帧代价 {frame_class} 不在可求和范围内')
                return {'expression': expression, 'solution': 'UNKNOWN', 'class': None,
                        'method': 'SUMMATION', 'notes': notes}
            return {'expression': expression, 'solution': _theta(time_class),
                    'class': time_class, 'method': 'SUMMATION', 'notes': notes}
        if branching == 2:
            return {'expression': expression, 'solution': 'Θ(2^n)', 'class': 'O(2^n)',
                    'method': 'EXPONENTIAL', 'notes': notes}
        notes.append(f'每层 {branching} 路递减递归给出 Θ({branching}^n)，目录中没有对应该底数的类别')
        return {'expression': expression, 'solution': f'Θ({branching}^n)', 'class': None,
                'method': 'EXPONENTIAL', 'notes': notes}
    if shrink == 'CONSTANT':
        # The recursive argument does not depend on n, so the recursion unfolds a
        # constant number of times; the frame's own work is the whole cost.
        expression = _recurrence_expression(branching, '1', frame_class)
        return {'expression': expression, 'solution': _theta(frame_class),
                'class': frame_class, 'method': 'CONSTANT_ARGUMENT', 'notes': notes}
    return {'expression': None, 'solution': 'UNKNOWN', 'class': None, 'method': 'NONE',
            'notes': ['递归结构未识别']}


def _solve_master(branching: int, b: float, frame_class: str, expression: str,
                  notes: list[str]) -> dict:
    critical = math.log(branching) / math.log(b) if b > 1 else 0.0
    exponent, has_log = _frame_exponent(frame_class)
    epsilon = 1e-9
    if critical > exponent + epsilon:
        time_class = describe_exponent(critical)
        power = _format_number(critical)
        if abs(critical - 1.0) <= epsilon:
            power = 'n'
            if critical == 1:
                solution = 'Θ(n)'
                return {'expression': expression, 'solution': solution,
                        'class': time_class, 'method': 'MASTER', 'notes': notes}
        else:
            power = f'n^{power}'
        if abs(critical - round(critical)) > epsilon:
            notes.append(f'递推临界指数为 {critical:.3f}，目录中最小的上界类别是 {time_class}')
        return {'expression': expression, 'solution': f'Θ({power})',
                'class': time_class, 'method': 'MASTER', 'notes': notes}
    if abs(critical - exponent) <= epsilon:
        if exponent == 0.0 and not has_log:
            return {'expression': expression, 'solution': 'Θ(log n)', 'class': 'O(log n)',
                    'method': 'MASTER', 'notes': notes}
        if exponent == 1.0 and not has_log:
            return {'expression': expression, 'solution': 'Θ(n log n)', 'class': 'O(n log n)',
                    'method': 'MASTER', 'notes': notes}
        if exponent == 2.0 and not has_log:
            return {'expression': expression, 'solution': 'Θ(n^2 log n)',
                    'class': 'O(n^2 log n)', 'method': 'MASTER', 'notes': notes}
        # The frame cost already carries a log factor, so the equal case gains a
        # second one (n log^2 n and friends). The vocabulary stops at one log per
        # power, so the report states the derived form and the nearest upper class.
        upper = {0.0: 'O(n)', 1.0: 'O(n^2)', 2.0: 'O(n^3)'}.get(exponent, 'O(n^3)')
        notes.append(f'推导结果为 {frame_class} 与递归同阶相乘后多出一个 log 因子，'
                     f'目录中最小的上界类别是 {upper}')
        return {'expression': expression, 'solution': f'Θ({_log_power(exponent, 2)})',
                'class': upper, 'method': 'MASTER', 'notes': notes}
    # The frame cost dominates the recursion tree; its own class survives.
    return {'expression': expression, 'solution': _theta(frame_class), 'class': frame_class,
            'method': 'MASTER', 'notes': notes}


def _log_power(exponent: float, logs: int) -> str:
    base = {0.0: '', 1.0: 'n', 2.0: 'n^2', 3.0: 'n^3'}.get(exponent, 'n^3')
    suffix = 'log n' if logs == 1 else f'log^{logs} n'
    return f'{base} {suffix}'.strip()



def _frame_exponent(frame_class: str) -> tuple[float, bool]:
    return {
        'O(1)': (0.0, False),
        'O(log n)': (0.0, True),
        'O(n)': (1.0, False),
        'O(n log n)': (1.0, True),
        'O(n^2)': (2.0, False),
    }.get(frame_class, (0.0, False))


def _round(value: float) -> float:
    return round(value)


def _theta(class_name: str) -> str:
    return f'Θ({class_name[2:-1]})' if class_name.startswith('O(') and class_name.endswith(')') else f'Θ({class_name})'


def _recurrence_expression(branching: int, inner: str, frame_class: str) -> str:
    coefficient = '' if branching == 1 else f'{branching}·'
    return f'T(n) = {coefficient}T({inner}) + {frame_class}'


def _format_number(value: float) -> str:
    if abs(value - round(value)) < 1e-9:
        return str(int(round(value)))
    return f'{value:.3f}'.rstrip('0').rstrip('.')
