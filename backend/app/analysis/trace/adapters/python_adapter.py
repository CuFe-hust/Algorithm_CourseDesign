"""Python trace adapter: counts executed lines, jumps and priced library calls.

The runner (``python_runner.py``) is a separate ``python3 -I`` process. This
module owns the ladder loop, the work budget, the memory pass and the conversion
from the runner's JSON into :class:`~app.analysis.trace.schema.LadderTrace`.

Budget: counting is cheap but not free (roughly a million events per second for
this interpreter), so a rung is kept only while the cumulative work stays under
:data:`WORK_BUDGET`. When a doubling would blow the budget the ladder stops; a
smaller number of rungs is not a problem because the counts are exact, but the
fitter is told how many it got.
"""
from __future__ import annotations

import shutil
import time
from pathlib import Path

from app.analysis import probe
from app.judge import config as judge_config

from .. import execution, schema

NAME = 'python-monitoring-v1'
WORK_UNIT = 'LINE+JUMP+库函数折算'
WORK_BUDGET = 2_000_000
RUNG_WALL_LIMIT_MS = 10_000
MEMORY_WALL_LIMIT_MS = 5_000
# ``tracemalloc`` slows allocations down, so at large rungs the memory pass costs
# more than the counted pass. The space class is visible well below this limit
# (three rungs are enough), so larger rungs skip it.
MEMORY_MAX_N = 2048
# Two runs of the same rung that differ by less than this are treated as
# deterministic. Randomised or data-dependent programs exceed it and say so.
DETERMINISM_TOLERANCE = 0.02


# The minimal program every valid solution has to be able to parse its input
# with. Its trace is subtracted from the submission's so that reading n tokens
# does not make every program look linear. Counting makes the subtraction exact
# arithmetic; no ratio threshold or "upper bound only" verdict is involved.
BASELINE_SOURCE = 'import sys\ndata = sys.stdin.buffer.read().split()\n'


def collect(source: str, rungs: list[probe.Rung], *, deadline: float,
            seed: int = 0) -> schema.LadderTrace:
    trace = schema.LadderTrace(language='python3', adapter=NAME, work_unit=WORK_UNIT)
    workdir = Path(judge_config.work_root()) / f'cxpy-{seed}-{int(time.time() * 1000)}'
    workdir.mkdir(parents=True, exist_ok=True)
    source_path = workdir / 'main.py'
    runner = Path(__file__).with_name('python_runner.py')
    total_work = 0.0
    try:
        source_path.write_text(source, encoding='utf-8')
        for rung in rungs:
            remaining_ms = int((deadline - time.monotonic()) * 1000)
            if remaining_ms < 500:
                trace.stop_reason = 'BUDGET_EXHAUSTED'
                break
            point = _measure_work(runner, source_path, workdir, rung, remaining_ms)
            trace.points.append(point)
            if point.verdict != 'OK':
                trace.stop_reason = point.verdict
                break
            total_work += point.work
            if rung.n <= MEMORY_MAX_N:
                peak = _measure_memory(runner, source_path, workdir, rung,
                                       min(remaining_ms, MEMORY_WALL_LIMIT_MS))
                point.peak_bytes = peak
            point.baseline_work = _measure_baseline(runner, workdir, rung, remaining_ms)
            if total_work >= WORK_BUDGET and len(trace.ok_points) >= 4:
                break
        if len(trace.ok_points) < 4:
            if trace.stop_reason == 'OK':
                trace.stop_reason = 'BUDGET_EXHAUSTED'
            trace.notes.append(f'只完成 {len(trace.ok_points)} 个档位，档位数不足')
        else:
            _check_determinism(trace, runner, source_path, workdir, rungs, deadline)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    return trace


def _measure_work(runner: Path, source_path: Path, workdir: Path, rung: probe.Rung,
                  remaining_ms: int) -> schema.TracePoint:
    result_path = workdir / f'work-{rung.n}.json'
    if result_path.exists():
        result_path.unlink()
    command = [judge_config.python_executable(), '-I', str(runner), str(source_path),
               'work', str(result_path)]
    outcome = execution.run(command, workdir, rung.input_text.encode('utf-8'),
                            min(RUNG_WALL_LIMIT_MS, max(500, remaining_ms)))
    payload = _read_result(result_path)
    if outcome.timed_out:
        return schema.TracePoint(n=rung.n, verdict='TIME_LIMIT_EXCEEDED',
                                 detail=f'{min(RUNG_WALL_LIMIT_MS, remaining_ms)} ms 内未结束')
    if payload is None:
        return schema.TracePoint(n=rung.n, verdict='RUNTIME_ERROR',
                                 detail=f'执行器没有写出结果（退出码 {outcome.returncode}）')
    verdict = payload.get('verdict', 'OK')
    if verdict != 'OK':
        return schema.TracePoint(n=rung.n, verdict=verdict, detail=payload.get('detail'))
    point = _to_point(rung.n, payload)
    if point.work <= 0:
        return schema.TracePoint(n=rung.n, verdict='RUNTIME_ERROR', detail='轨迹中没有记录到任何工作量')
    return point


def _measure_baseline(runner: Path, workdir: Path, rung: probe.Rung,
                      remaining_ms: int) -> float:
    baseline_path = workdir / 'baseline.py'
    if not baseline_path.exists():
        baseline_path.write_text(BASELINE_SOURCE, encoding='utf-8')
    result_path = workdir / f'base-{rung.n}.json'
    if result_path.exists():
        result_path.unlink()
    command = [judge_config.python_executable(), '-I', str(runner), str(baseline_path),
               'work', str(result_path)]
    outcome = execution.run(command, workdir, rung.input_text.encode('utf-8'),
                            min(3000, max(500, remaining_ms)))
    if outcome.timed_out:
        return 0.0
    payload = _read_result(result_path)
    if payload is None or payload.get('verdict') != 'OK':
        return 0.0
    return float(payload.get('work') or 0.0)


def _measure_memory(runner: Path, source_path: Path, workdir: Path, rung: probe.Rung,
                    remaining_ms: int) -> int | None:
    result_path = workdir / f'mem-{rung.n}.json'
    if result_path.exists():
        result_path.unlink()
    command = [judge_config.python_executable(), '-I', str(runner), str(source_path),
               'memory', str(result_path)]
    outcome = execution.run(command, workdir, rung.input_text.encode('utf-8'),
                            max(500, remaining_ms), capture_rss=False)
    if outcome.timed_out:
        return None
    payload = _read_result(result_path)
    if payload is None or payload.get('verdict') != 'OK':
        return None
    peak = payload.get('peak_bytes')
    return int(peak) if peak else None


def _read_result(path: Path) -> dict | None:
    try:
        import json
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None


def _to_point(n: int, payload: dict) -> schema.TracePoint:
    point = schema.TracePoint(
        n=n,
        work=float(payload.get('work', 0)),
        line_events=int(payload.get('line_events', 0)),
        jump_events=int(payload.get('jump_events', 0)),
        library_work=float(payload.get('library_work', 0)),
        max_depth=int(payload.get('max_depth', 0)),
        lines={str(key): int(value) for key, value in (payload.get('lines') or {}).items()},
        opaque_calls={str(key): int(value) for key, value in (payload.get('opaque_calls') or {}).items()},
    )
    for name, raw in (payload.get('functions') or {}).items():
        function = schema.FunctionTrace(name=name,
                                        calls=int(raw.get('calls', 0)),
                                        callers={str(key): int(value)
                                                 for key, value in (raw.get('callers') or {}).items()})
        for sample in raw.get('samples') or []:
            function.add_sample(schema.FrameSample(
                args=tuple(int(value) for value in sample.get('args') or ()),
                cost=float(sample.get('cost', 0)),
                children=tuple(tuple(int(value) for value in child)
                               for child in sample.get('children') or ())))
        point.functions[name] = function
    return point


def _check_determinism(trace: schema.LadderTrace, runner: Path, source_path: Path,
                       workdir: Path, rungs: list[probe.Rung], deadline: float) -> None:
    """Re-run the last completed rung and compare total work.

    Exact counts mean a deterministic program repeats to the last unit; a
    difference means the program's work depends on randomness or on values that
    the generated input does not fix. The report says so instead of pretending
    the number is stable.
    """
    completed = [point for point in trace.ok_points]
    if not completed:
        return
    last = completed[-1]
    rung = next((candidate for candidate in rungs if candidate.n == last.n), None)
    if rung is None:
        return
    remaining_ms = int((deadline - time.monotonic()) * 1000)
    if remaining_ms < 1000:
        return
    repeat = _measure_work(runner, source_path, workdir, rung, min(5000, remaining_ms))
    if repeat.verdict != 'OK' or repeat.work <= 0:
        return
    delta = abs(repeat.work - last.work) / max(last.work, 1.0)
    trace.repeat_delta = delta
    trace.deterministic = delta <= DETERMINISM_TOLERANCE
