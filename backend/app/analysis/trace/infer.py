"""Turn a ladder of exact work counts into the verdict shown to users.

Two estimates are computed and cross-checked:

* the closed form of the *total* work, fitted over all rungs. This is the
  primary answer and works for iterative and recursive programs alike;
* a recurrence read from the call trace for recursive programs, solved into a
  closed form.

When both exist and agree, the recurrence is published as the explanation and
the class is the one both produced. When they disagree, the total-work fit wins
(it observes the whole program, while the recurrence may describe only one
recursive helper) and the disagreement is written into the notes. When the
recurrence has no nameable class in the platform vocabulary (``3^n``,
``log^2 n``) the derived form is still stated, with the nearest published bound.

Space is fitted from peak allocation and, when the trace has it, from how the
maximum recursion depth grows. The two are combined by taking the larger class:
a program can be heap-light and stack-heavy.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .classes import CLASS_RANK, describe_exponent, greater
from .fit import ClassFit, fit_depth, fit_growth, fit_space
from .recurrence import Recurrence, infer_recurrence
from .schema import LadderTrace, TracePoint

# A line's own growth class is only reported when at least this many rungs
# executed it; fewer points cannot tell "grows with n" from "executed once".
MIN_LINE_POINTS = 4
MAX_EVIDENCE_LINES = 6


@dataclass
class TimeConclusion:
    time_class: str
    confidence: str
    method: str
    closed_form: str
    fit: ClassFit
    recurrence: Recurrence | None = None
    notes: list[str] = field(default_factory=list)

    def to_payload(self) -> dict:
        return {
            'class': self.time_class,
            'confidence': self.confidence,
            'method': self.method,
            'closed_form': self.closed_form,
            'recurrence': None if self.recurrence is None else self.recurrence.to_payload(),
            'fit': self.fit.to_payload(),
            'notes': list(self.notes),
        }


@dataclass
class SpaceConclusion:
    space_class: str
    confidence: str
    source: str
    fit: ClassFit
    depth_fit: ClassFit | None = None
    notes: list[str] = field(default_factory=list)

    def to_payload(self) -> dict:
        return {
            'class': self.space_class,
            'confidence': self.confidence,
            'source': self.source,
            'fit': self.fit.to_payload(),
            'depth_fit': None if self.depth_fit is None else self.depth_fit.to_payload(),
            'notes': list(self.notes),
        }


@dataclass
class TraceConclusion:
    time: TimeConclusion
    space: SpaceConclusion
    evidence: list[dict] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)

    def to_payload(self) -> dict:
        return {
            'time': self.time.to_payload(),
            'space': self.space.to_payload(),
            'evidence': list(self.evidence),
            'limitations': list(self.limitations),
        }


def infer(ladder: LadderTrace, *, language_label: str = '') -> TraceConclusion:
    usable = ladder.ok_points
    limitations: list[str] = []
    if not usable:
        return TraceConclusion(
            time=TimeConclusion('UNKNOWN', 'LOW', 'UNKNOWN', 'UNKNOWN',
                                ClassFit('UNKNOWN', 'LOW', notes=['没有完成的测量档位'])),
            space=SpaceConclusion('UNKNOWN', 'LOW', 'NONE', ClassFit('UNKNOWN', 'LOW')),
            limitations=['所有档位都没有完成执行，无法估计增长'])

    baseline_present = any(point.baseline_work > 0 for point in usable)
    if baseline_present:
        limitations.append(
            '工作量已减去输入解析基准（同一输入上典型读法的执行计数），报告的类别描述算法本身，'
            '不含把输入读进来的开销')
    closed = _fit_total(usable, baseline_present, limitations)
    closed = _guard_data_dependent(usable, baseline_present, closed, limitations)
    recurrence = infer_recurrence(usable)
    library_fit = _fit_called_library(usable, ladder)
    time_conclusion = _combine_time(closed, recurrence, limitations, language_label,
                                    library_fit)
    space_conclusion = _combine_space(usable, limitations)
    evidence = _line_evidence(usable, time_conclusion.time_class, limitations)
    if recurrence is not None:
        evidence.insert(0, {
            'kind': 'RECURSION',
            'function': recurrence.function,
            'branching': recurrence.branching,
            'shrink': recurrence.shrink,
            'expression': recurrence.expression,
            'solution': recurrence.solution,
            'share': round(recurrence.share, 3),
        })
    limitations.extend(_ladder_limitations(ladder, usable))
    return TraceConclusion(time=time_conclusion, space=space_conclusion,
                           evidence=evidence, limitations=_dedupe(limitations))


def _theta(class_name: str) -> str:
    if class_name.startswith('O(') and class_name.endswith(')'):
        return f'Θ({class_name[2:-1]})'
    return f'Θ({class_name})'


def _fit_total(points: list[TracePoint], baseline_present: bool,
               limitations: list[str]) -> ClassFit:
    """Fit the growth of the work *above* input parsing.

    Every valid solution has to read the input, and reading n tokens is linear
    whether or not the algorithm is. The adapter traces a minimal reader on the
    same generated input, so this subtraction is exact arithmetic on counts. If a
    program's own work never rises above the reader, the algorithm is constant on
    this input family; if only a couple of rungs are above, the total (including
    reading) is fitted and the report says the class includes the reading.
    """
    raw = fit_growth([(point.n, point.work) for point in points])
    if not baseline_present:
        return raw
    effective = [(point.n, point.work - point.baseline_work) for point in points]
    positive = [(n, work) for n, work in effective if work > 0]
    if not positive:
        if raw.time_class not in ('UNKNOWN', 'O(1)') and raw.confidence in ('MEDIUM', 'HIGH'):
            limitations.append('算法自身的工作量没有超过输入解析基准，时间类别按含读入的总工作量报告')
            return raw
        limitations.append('扣除输入解析基准后，工作量在全部档位上是常数，算法自身为常数级')
        return ClassFit('O(1)', 'MEDIUM', notes=['工作量没有随 n 增长'])
    if len(positive) >= 3:
        fit = fit_growth(positive)
        if fit.time_class != 'UNKNOWN':
            return fit
    limitations.append('超过输入解析基准的档位不足 3 个，时间类别按含读入的总工作量报告')
    return raw


def _guard_data_dependent(points: list[TracePoint], baseline_present: bool,
                          fit: ClassFit, limitations: list[str]) -> ClassFit:
    """Refuse to publish a confident class when the work falls as n grows.

    Exact counts remove timer noise, but they cannot remove the fact that some
    programs do different amounts of work on different *values*: an early-exit
    loop, a graph search that finds its answer after a few relaxations, a jump
    game. A dip between two consecutive rungs is the visible symptom. A modest dip
    only costs confidence; a large one means the class describes neither size nor
    a stable input family, so the report says the work is value-dependent instead
    of printing a number.
    """
    effective = []
    for point in points:
        baseline = point.baseline_work if baseline_present else 0.0
        effective.append((point.n, point.work - baseline))
    drop = 0.0
    for (_, previous), (_, current) in zip(effective, effective[1:]):
        if previous > 0 and current < previous:
            drop = max(drop, (previous - current) / previous)
    if drop < 0.15:
        return fit
    note = (f'工作量在相邻档位之间下降了 {drop:.0%}，说明执行路径受输入数值影响，'
            '不只是由输入规模决定')
    if drop >= 0.30:
        limitations.append(note + '；本报告不给出确定的增长类别')
        return ClassFit('UNKNOWN', 'LOW', candidates=fit.candidates,
                        notes=[note + '；类别无法只由规模解释'])
    limitations.append(note + '；类别只作参考')
    fit.confidence = 'LOW'
    fit.notes = list(fit.notes) + [note + '；类别只作参考']
    return fit


def _fit_called_library(points: list[TracePoint], ladder: LadderTrace) -> ClassFit | None:
    """Fit the growth of work priced for calls whose implementation is invisible.

    For C/C++ the libc++ sorting instantiations live in the precompiled library,
    so the adapter prices them from the call count and the rung size. That priced
    series is an independent lower bound on the program's growth: reading n
    values is linear, but a sort over them is not. Fitting it separately keeps
    the estimate honest without letting the input-parsing baseline decide the
    class. Python prices its builtins *inside* the total (and the input reader is
    subtracted from that total), so the same series would only repeat the parsed
    input cost; the merge is therefore limited to the native adapter.
    """
    if not ladder.adapter.startswith('native'):
        return None
    series = [(point.n, point.library_work) for point in points if point.library_work > 0]
    if len(series) < 3:
        return None
    fit = fit_growth(series)
    return fit if fit.time_class != 'UNKNOWN' else None


def _combine_time(closed: ClassFit, recurrence: Recurrence | None, limitations: list[str],
                  language_label: str,
                  library_fit: ClassFit | None = None) -> TimeConclusion:
    notes = list(closed.notes)
    time_class = closed.time_class
    confidence = closed.confidence
    method = 'CLOSED_FORM' if time_class != 'UNKNOWN' else 'UNKNOWN'
    closed_form = _theta(time_class) if time_class != 'UNKNOWN' else 'UNKNOWN'
    if recurrence is not None and recurrence.time_class is not None:
        recurrence_class = recurrence.time_class
        if time_class == 'UNKNOWN':
            time_class = recurrence_class
            confidence = 'MEDIUM'
            method = 'RECURRENCE'
            closed_form = recurrence.solution or _theta(recurrence_class)
            notes.append('总工作量的闭式拟合没有结论，时间类别由递推式给出')
        elif CLASS_RANK.get(recurrence_class, -1) > CLASS_RANK.get(time_class, -1):
            notes.append(
                f'递推式给出 {recurrence_class}，总工作量拟合给出 {time_class}；'
                '递推式可能只描述了部分调用路径，时间类别以总工作量为准')
        elif CLASS_RANK.get(recurrence_class, -1) < CLASS_RANK.get(time_class, -1):
            notes.append(
                f'递推式只描述递归部分（{recurrence_class}），程序还有同阶或更高阶的循环工作；'
                f'时间类别以总工作量拟合 {time_class} 为准')
        else:
            method = 'RECURRENCE'
            closed_form = recurrence.solution or _theta(time_class)
            if confidence in ('MEDIUM', 'LOW') and recurrence.frame_confidence in ('HIGH', 'MEDIUM'):
                confidence = 'MEDIUM'
    elif recurrence is not None and recurrence.solution:
        notes.append(f'提取到递推关系 {recurrence.expression}，闭式 {recurrence.solution}；'
                     '该形态在类别目录中没有对应条目，按总工作量拟合报告')
    if library_fit is not None and library_fit.time_class != 'UNKNOWN':
        if CLASS_RANK.get(library_fit.time_class, -1) > CLASS_RANK.get(time_class, -1):
            notes.append(
                f'标准库算法的内部工作不在轨迹里，按输入规模折算出的增长为 '
                f'{library_fit.time_class}，高于其余可观测工作给出的 {time_class}；'
                '时间类别取两者较高的一档')
            time_class = library_fit.time_class
            closed_form = f'Θ({time_class[2:-1]})' if time_class.startswith('O(') \
                else f'Θ({time_class})'
            method = 'CLOSED_FORM'
        if time_class != 'UNKNOWN':
            confidence = 'MEDIUM' if confidence == 'HIGH' else confidence
            notes.append('标准库调用部分是按理论代价折算的估计，因此置信度不超过中')
    if language_label:
        notes.append(f'轨迹采集自 {language_label} 程序的真实执行')
    return TimeConclusion(time_class=time_class, confidence=confidence, method=method,
                          closed_form=closed_form, fit=closed, recurrence=recurrence,
                          notes=notes)


def _combine_space(points: list[TracePoint], limitations: list[str]) -> SpaceConclusion:
    memory_points = [(point.n, point.peak_bytes) for point in points if point.peak_bytes]
    depth_points = [(point.n, point.max_depth) for point in points if point.max_depth]
    if not memory_points and not depth_points:
        return SpaceConclusion('UNKNOWN', 'LOW', 'NONE', ClassFit('UNKNOWN', 'LOW'),
                               notes=['该语言的采集器没有提供空间数据'])
    heap_fit = fit_space(memory_points) if memory_points else ClassFit('UNKNOWN', 'LOW')
    depth_fit = fit_depth(depth_points) if len(depth_points) >= 3 else None
    space_class = heap_fit.time_class
    confidence = heap_fit.confidence
    source = 'TRACE'
    notes = list(heap_fit.notes)
    if depth_fit is not None and depth_fit.time_class not in ('UNKNOWN', 'O(1)'):
        if CLASS_RANK.get(depth_fit.time_class, -1) > CLASS_RANK.get(space_class, -1):
            notes.append(f'峰值分配为 {space_class}，但递归深度按 {depth_fit.time_class} 增长，'
                         '空间类别取两项中较高的一档')
            space_class = depth_fit.time_class
            confidence = 'MEDIUM' if confidence == 'LOW' else confidence
    if not memory_points:
        notes.append('没有峰值分配数据，空间类别只依据递归深度')
        confidence = 'LOW'
    if space_class == 'UNKNOWN':
        limitations.append('空间增长无法匹配任何类别，报告不给出空间结论')
    return SpaceConclusion(space_class, confidence, source, heap_fit, depth_fit, notes)


def _line_evidence(points: list[TracePoint], time_class: str,
                   limitations: list[str]) -> list[dict]:
    """Name the source lines whose execution counts grew with the input.

    For an iterative program this is the explanation: which loop body carried the
    work. The location string is ``function:line``; the line's own class comes
    from fitting its count across rungs, so "this line ran Θ(n^2) times" is
    measured, not inferred from the block shape.
    """
    locations = {location for point in points for location in point.lines}
    rows: list[dict] = []
    for location in locations:
        series = [(point.n, point.lines[location]) for point in points
                  if location in point.lines and point.lines[location] > 0]
        if len(series) < MIN_LINE_POINTS:
            continue
        fit = fit_growth(series)
        if fit.time_class == 'UNKNOWN':
            continue
        rows.append({'kind': 'LINE', 'location': location, 'class': fit.time_class,
                     'counts': [{'n': n, 'count': count} for n, count in series],
                     'final_count': series[-1][1]})
    rows.sort(key=lambda row: (CLASS_RANK.get(row['class'], -1), row['final_count']), reverse=True)
    if rows:
        dominant = [row for row in rows if row['class'] == time_class]
        selected = dominant[:MAX_EVIDENCE_LINES] or rows[:MAX_EVIDENCE_LINES]
        for row in selected:
            row.pop('final_count', None)
        return selected
    return []


def _ladder_limitations(ladder: LadderTrace, points: list[TracePoint]) -> list[str]:
    limitations: list[str] = []
    if ladder.stop_reason == 'BUDGET_EXHAUSTED':
        limitations.append('轨迹计数预算用尽，档位数少于计划')
    elif ladder.stop_reason == 'TIME_LIMIT_EXCEEDED':
        limitations.append('最大档位触发了单档时间上限，后续档位没有测量')
    elif ladder.stop_reason == 'RUNTIME_ERROR':
        limitations.append('某一档执行出错，后续档位没有测量')
    elif ladder.stop_reason == 'NO_LADDER':
        limitations.append('该题没有可用的规模伸缩输入')
    if len(points) < 5:
        limitations.append(f'有效档位只有 {len(points)} 个，增长类别的置信度不会高于中')
    if ladder.deterministic is False:
        limitations.append('同一档位重复执行的计数不一致（程序含随机或依赖数据的分支），'
                           '类别按多次运行的中位形态报告')
    return limitations


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result
