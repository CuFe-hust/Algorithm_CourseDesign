"""Stand-alone trace runner for Python submissions.

This file is executed as a separate process (``python3 -I python_runner.py ...``)
so it must not import anything from the application. It runs the student source
in a controllable way and writes one JSON result:

* ``mode == work``: installs ``sys.monitoring`` local events on *only* the code
  objects compiled from the student source, then counts executed lines, loop
  back-edges and known-cost library calls. Line events alone are not enough: a
  loop written on one line produces a single line event, so jump events are what
  count iterations.
* ``mode == memory``: runs the same program under ``tracemalloc`` and reports the
  peak allocation. This is a separate process on purpose — in work mode the
  tracer's own bookkeeping would otherwise be counted as the submission's
  memory.

Everything the program prints goes to real stdout, which the parent drains and
discards. The result is written to a file so program output cannot corrupt it.
"""
from __future__ import annotations

import io
import json
import math
import os
import sys
import tracemalloc

# Library calls whose cost depends on the size of their first argument. The
# trace cannot see inside a C implementation, so the size is read from the call
# event and the cost is the textbook cost of that operation. A call whose name is
# not here is treated as O(1) and recorded as an unpriced library call, which
# lowers the confidence instead of silently counting it as work.
LIBRARY_COSTS = {
    'sorted': lambda size: size * math.log2(max(2, size)),
    'sort': lambda size: size * math.log2(max(2, size)),
    'heapify': lambda size: size,
    'heappush': lambda size: math.log2(max(2, size)),
    'heappop': lambda size: math.log2(max(2, size)),
    'nlargest': lambda size: size,
    'nsmallest': lambda size: size,
    'bisect': lambda size: math.log2(max(2, size)),
    'bisect_left': lambda size: math.log2(max(2, size)),
    'bisect_right': lambda size: math.log2(max(2, size)),
    'insort': lambda size: size,
    'insort_left': lambda size: size,
    'insort_right': lambda size: size,
    'sum': lambda size: size,
    'max': lambda size: size,
    'min': lambda size: size,
    'any': lambda size: size,
    'all': lambda size: size,
    'join': lambda size: size,
    'list': lambda size: size,
    'tuple': lambda size: size,
    'set': lambda size: size,
    'dict': lambda size: size,
    'frozenset': lambda size: size,
    'reversed': lambda size: size,
    'copy': lambda size: size,
    'clear': lambda size: size,
    'reverse': lambda size: size,
    'count': lambda size: size,
    'index': lambda size: size,
    'find': lambda size: size,
    'rfind': lambda size: size,
    'replace': lambda size: size,
    'split': lambda size: size,
    'strip': lambda size: size,
    'lower': lambda size: size,
    'upper': lambda size: size,
}

MAX_SAMPLE_RECORDS = 480
MAX_LINE_RECORDS = 4000


def _frame_argument_size(value):
    """Argument size for the recurrence: an integer is its own value.

    ``def fib(n)`` recurses on the *value* of n, so the trace must record the
    integer itself; this is the only place where an integer is a size.
    """
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    try:
        return len(value)
    except TypeError:
        return 0


def _call_argument_size(value):
    """Size of the first argument of a library call.

    A container's length is the size the priced operation works on. An integer is
    a scalar there: ``max(x, y)`` over two numbers is O(1), not O(x). Treating it
    as a size turned every ``max`` in a loop into quadratic work.
    """
    if isinstance(value, (str, bytes, bytearray, list, tuple, set, frozenset, dict)):
        return len(value)
    return 0


def _code_objects(root):
    stack = [root]
    while stack:
        code = stack.pop()
        yield code
        for constant in code.co_consts:
            if hasattr(constant, 'co_code'):
                stack.append(constant)


class WorkCollector:
    def __init__(self):
        self.student_codes: set = set()
        self.stack: list[dict] = []
        self.functions: dict[str, dict] = {}
        self.lines: dict[str, int] = {}
        self.opaque: dict[str, int] = {}
        self.line_events = 0
        self.jump_events = 0
        self.library_work = 0.0
        self.max_depth = 0

    def register(self, root) -> None:
        self.student_codes = set(_code_objects(root))

    def _frame(self):
        return self.stack[-1] if self.stack else None

    def on_start(self, code, offset):
        if code not in self.student_codes:
            return
        frame = sys._getframe(1)
        names = code.co_varnames[:code.co_argcount]
        arguments = tuple(_frame_argument_size(frame.f_locals.get(name)) for name in names)
        self.stack.append({'name': code.co_name, 'args': arguments, 'own': 0.0, 'children': []})
        self.max_depth = max(self.max_depth, len(self.stack))

    def on_return(self, code, offset, value):
        if code not in self.student_codes:
            return
        if not self.stack:
            return
        record = self.stack.pop()
        self._finish(record)

    def _finish(self, record: dict) -> None:
        name = record['name']
        recursive = tuple(child[1] for child in record['children'] if child[0] == name)
        standalone = record['own'] + sum(child[2] for child in record['children']
                                         if child[0] != name)
        subtree = record['own'] + sum(child[2] for child in record['children'])
        parent = self._frame()
        stats = self.functions.get(name)
        if stats is None:
            stats = {'calls': 0, 'callers': {}, 'samples': []}
            self.functions[name] = stats
        stats['calls'] += 1
        caller = parent['name'] if parent else '<module>'
        stats['callers'][caller] = stats['callers'].get(caller, 0) + 1
        samples = stats['samples']
        if len(samples) <= MAX_SAMPLE_RECORDS * 2:
            samples.append((record['args'], standalone, recursive))
            if len(samples) > MAX_SAMPLE_RECORDS * 2:
                del samples[1::2]
        if parent is not None:
            parent['children'].append((name, record['args'], subtree))

    def on_line(self, code, lineno):
        if code not in self.student_codes:
            return
        self.line_events += 1
        frame = self._frame()
        if frame is not None:
            frame['own'] += 1.0
        key = f'{code.co_name}:{lineno}'
        if key in self.lines:
            self.lines[key] += 1
        elif len(self.lines) < MAX_LINE_RECORDS:
            self.lines[key] = 1

    def on_jump(self, code, source, destination):
        if code not in self.student_codes:
            return
        self.jump_events += 1
        frame = self._frame()
        if frame is not None:
            frame['own'] += 1.0

    def on_call(self, code, offset, callable_object, arg0):
        if code not in self.student_codes:
            return
        if getattr(callable_object, '__code__', None) in self.student_codes:
            return
        name = getattr(callable_object, '__name__', None)
        cost_function = LIBRARY_COSTS.get(name)
        if cost_function is None:
            key = name or type(callable_object).__name__
            self.opaque[key] = self.opaque.get(key, 0) + 1
            return
        cost = float(cost_function(_call_argument_size(arg0)))
        self.library_work += cost
        frame = self._frame()
        if frame is not None:
            frame['own'] += cost

    def on_unwind(self, code, offset, exception):
        if code in self.student_codes and self.stack:
            self.stack.pop()

    def payload(self) -> dict:
        functions = {}
        for name, stats in self.functions.items():
            functions[name] = {
                'calls': stats['calls'],
                'callers': stats['callers'],
                'samples': [
                    {'args': list(args), 'cost': round(cost, 3),
                     'children': [list(child) for child in children]}
                    for args, cost, children in stats['samples']
                ],
            }
        return {
            'line_events': self.line_events,
            'jump_events': self.jump_events,
            'library_work': round(self.library_work, 3),
            'max_depth': self.max_depth,
            'functions': functions,
            'lines': self.lines,
            'opaque_calls': self.opaque,
        }


def _monitoring_tool_id():
    for tool in (sys.monitoring.PROFILER_ID, sys.monitoring.OPTIMIZER_ID,
                 sys.monitoring.DEBUGGER_ID, 4, 5):
        try:
            sys.monitoring.use_tool_id(tool, 'complexity-trace')
            return tool
        except ValueError:
            continue
    raise RuntimeError('没有可用的 sys.monitoring 工具编号')


def run_work(source: str, source_name: str) -> dict:
    events = sys.monitoring.events
    # PY_UNWIND is a global-only event (PEP 669); everything else is local to the
    # student's code objects, so the tracer itself is never counted.
    wanted = events.LINE | events.JUMP | events.PY_START | events.PY_RETURN | events.CALL
    code = compile(source, source_name, 'exec')
    collector = WorkCollector()
    collector.register(code)
    tool = _monitoring_tool_id()
    try:
        callbacks = (
            (events.PY_START, collector.on_start),
            (events.PY_RETURN, collector.on_return),
            (events.PY_UNWIND, collector.on_unwind),
            (events.LINE, collector.on_line),
            (events.JUMP, collector.on_jump),
            (events.CALL, collector.on_call),
        )
        for event, callback in callbacks:
            sys.monitoring.register_callback(tool, event, callback)
        for student_code in collector.student_codes:
            sys.monitoring.set_local_events(tool, student_code, wanted)
        sys.monitoring.set_events(tool, events.PY_UNWIND)
        _execute(code, source_name)
    finally:
        try:
            sys.monitoring.set_events(tool, 0)
        except ValueError:
            pass
        for student_code in collector.student_codes:
            try:
                sys.monitoring.set_local_events(tool, student_code, 0)
            except ValueError:
                pass
        try:
            sys.monitoring.free_tool_id(tool)
        except ValueError:
            pass
    payload = collector.payload()
    payload['work'] = payload['line_events'] + payload['jump_events'] + payload['library_work']
    return payload


def run_memory(source: str, source_name: str) -> dict:
    code = compile(source, source_name, 'exec')
    tracemalloc.start()
    try:
        _execute(code, source_name)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    return {'peak_bytes': int(peak)}


def _execute(code, source_name: str) -> None:
    global_context = {'__name__': '__main__', '__file__': source_name}
    sys.argv = [source_name]
    if sys.getrecursionlimit() < 20000:
        sys.setrecursionlimit(20000)
    exec(code, global_context)  # noqa: S102 - running the submission is the point


def main(argv) -> int:
    source_path, mode, result_path = argv[1], argv[2], argv[3]
    source = open(source_path, 'r', encoding='utf-8').read()
    result: dict = {'verdict': 'OK'}
    try:
        if mode == 'work':
            result.update(run_work(source, source_path))
        else:
            result.update(run_memory(source, source_path))
    except SyntaxError as error:
        result = {'verdict': 'COMPILATION_ERROR',
                  'detail': f'第 {error.lineno} 行语法错误：{error.msg}'[:400]}
    except SystemExit as error:
        if error.code not in (None, 0):
            result = {'verdict': 'RUNTIME_ERROR', 'detail': f'程序以退出码 {error.code} 结束'}
    except BaseException as error:  # noqa: BLE001 - reported, not raised
        message = f'{type(error).__name__}: {error}'
        result = {'verdict': 'RUNTIME_ERROR', 'detail': message[:400]}
    with open(result_path, 'w', encoding='utf-8') as handle:
        json.dump(result, handle, ensure_ascii=False)
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv))
