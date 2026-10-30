"""C/C++ trace adapter: counts instrumented source lines executed by gcov.

The submission is compiled once, at ``-O0`` with arc and line coverage, and is
then run once per rung. After each run :command:`gcov` turns the coverage data
into one ``*.gcov`` text file per source file that contributed code, and the
numeric execution counts in all of them are summed. That sum is the work unit.

The measured build differs from the graded build on purpose: the judge compiles
at ``-O2`` (fast, optimised, no instrumentation), while measurement needs one
counter per basic block. ``-O0`` is the only level at which the mapping from
counters to source lines is stable, and it is also what makes the standard
library's header-only algorithms part of the count: an instrumented header
contributes its executed lines exactly like student code, so "work" is total
executed source lines rather than a guess about library calls. ``-g`` is not
passed: on macOS it would emit a ``.dSYM`` bundle that nothing here reads.

The cost of that choice is that header-only bookkeeping dominates what a
container-based algorithm counts. Iterating a ``std::vector`` at ``-O0`` runs
roughly thirty instrumented lines per element of iterator and allocator code, so
a solution built on ``std::sort`` measures almost linear growth at these sizes
even though its comparison count is ``n log n``. Growth classes for hand-written
loops are unaffected; a library-only solution may be reported one class low.

The input parsing baseline is compiled from a minimal reader and measured on the
same input, so the fitter can subtract the cost of reading a larger input from
the algorithm's own work.

Space is measured exactly for C++: ``native_support/memwatch.cpp`` replaces the
global allocation functions and reports the peak number of live bytes the
program allocated. C has no such hook, so its points carry no peak.
"""
from __future__ import annotations

import json
import math
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

from app.analysis import probe
from app.judge import config as judge_config

from .. import execution, schema

NAME = 'native-gcov-v1'
WORK_UNIT = '执行插桩源码行数（gcov）'
# Cumulative executed-line budget for one report. A quadratic program at the
# largest rung can reach millions of counted lines, so the ladder stops here
# instead of walking into the next doubling.
WORK_BUDGET = 8_000_000
RUNG_WALL_LIMIT_MS = 10_000
COMPILE_TIMEOUT_MS = judge_config.COMPILE_WALL_MS
# gcov over one run's data is local file work; the guard only stops a hang.
GCOV_TIMEOUT_MS = 60_000
# Two runs of the same rung that differ by less than this are treated as
# deterministic. Randomised or input-dependent programs exceed it and say so.
DETERMINISM_TOLERANCE = 0.02
DIAGNOSTIC_LIMIT = 400
# The measurement build writes the peak-allocation JSON to this variable's path.
MEM_ENV = 'CX_MEM_OUT'
MEMWATCH_NAME = 'memwatch.cpp'
MEMWATCH_PATH = Path(__file__).with_name('native_support') / MEMWATCH_NAME
# ``<output>-<source stem>.gcno``: the executable is always ``main``.
GCNO_NAME = 'main-main.gcno'
GCNO_GLOB = 'main-*.gcno'

GCC = {'cpp': 'g++', 'c': 'gcc'}
STANDARD = {'cpp': 'c++17', 'c': 'c17'}
SOURCE_NAME = {'cpp': 'main.cpp', 'c': 'main.c'}

# The minimal program every valid solution has to be able to read its input
# with. Its counted lines are subtracted from the submission's, so reading n
# values does not make every program look linear.
#
# The C++ reader takes a number rather than a string on purpose. At ``-O0`` a
# ``std::string`` extraction executes several hundred instrumented header lines
# per token (locale facets, ``__extract_char``) while ``std::cin >> int`` costs
# about four, so a string reader subtracts roughly twenty times the parsing work
# a numeric solution actually pays. Measured on this machine, that over-count
# turned bubble sort into ``n^2 log n``: the subtraction removed most of the
# real quadratic term at small n. A numeric reader matches a numeric solution,
# and on input whose first token is not a number it stops immediately, leaving
# the ladder as if no baseline were known.
BASELINE_SOURCE = {
    'cpp': ('#include <iostream>\n'
            'int main(){std::ios::sync_with_stdio(false);std::cin.tie(nullptr);'
            'long long value=0;while(std::cin>>value){}}\n'),
    'c': '#include <stdio.h>\nint main(void){char b[65536];while(fgets(b,sizeof b,stdin)){}}\n',
}

# ------------------------------------------------------------------ libraries
#
# Apple's libc++ implements the sorting algorithms for primitive element types as
# explicit instantiations inside the precompiled library (``extern template ...
# __sort<__less<int>&, int*>``), so the student's call executes code that no
# compiler instrumentation in our translation unit can see. Measurements confirm
# it: a program that reads n ints and calls ``std::sort`` produces almost the
# same counted lines as a program that only reads them (151 extra lines at every
# n). Counting alone would therefore report ``O(n)`` for the most common C++
# solution in the course.
#
# The bounded answer is the same one the Python adapter uses for C-implemented
# builtins: price the call. The execution count of the call site comes from
# coverage data, the container size is approximated by the rung's input size, and
# the report says the estimate was made. This is a library cost table, not a
# structural guess about the program: it changes only calls that genuinely run.
LIBRARY_ALGORITHMS = {
    'sort': 'n log n',
    'stable_sort': 'n log n',
    'partial_sort': 'n log n',
    'sort_heap': 'n log n',
    'nth_element': 'n',
    'make_heap': 'n',
}
_LIBRARY_STEMS = '|'.join(LIBRARY_ALGORITHMS)
_QUALIFIED_CALL = re.compile(r'\bstd\s*::\s*(%s)\s*\(' % _LIBRARY_STEMS)
_BARE_CALL = re.compile(r'(?<![\w:.])(%s)\s*\(' % _LIBRARY_STEMS)


def library_call_lines(source: str) -> dict[int, str]:
    """Find ``std::sort``-family call sites in the student source.

    A bare ``sort(`` is only treated as the standard algorithm when the source
    includes ``<algorithm>`` and does not define its own function with that name;
    otherwise a student's own helper would be priced as a library call.
    """
    text = _strip_c_comments(source)
    includes_algorithm = bool(re.search(r'#\s*include\s*<(algorithm|bits/stdc\+\+\.h)>', text))
    defined = {name for name in LIBRARY_ALGORITHMS
               if re.search(r'\b(?:void|auto|bool|int|long|double|float|[\w:<>]+)\s+'
                            + name + r'\s*\(', text)}
    calls: dict[int, str] = {}
    for number, line in enumerate(text.splitlines(), start=1):
        qualified = _QUALIFIED_CALL.search(line)
        if qualified:
            calls[number] = qualified.group(1)
            continue
        if not includes_algorithm:
            continue
        bare = _BARE_CALL.search(line)
        if bare and bare.group(1) not in defined:
            calls[number] = bare.group(1)
    return calls


def _strip_c_comments(source: str) -> str:
    text = re.sub(r'/\*.*?\*/', ' ', source, flags=re.S)
    return re.sub(r'//[^\n]*', ' ', text)


def _apply_library_costs(trace: schema.LadderTrace, source: str, source_name: str) -> None:
    """Add the priced cost of invisible standard-library algorithm calls.

    A call site that runs a handful of times on every rung is almost always a
    single sort over the input; it is priced at the rung's ``n``. A call site
    that runs many times per rung is sorting small containers in a loop, so it is
    priced per call instead of per input element: multiplying those by ``n log n``
    would turn an ``O(n)`` bucket pass into ``O(n^2 log n)``.
    """
    call_lines = library_call_lines(source)
    if not call_lines:
        return
    per_point: list[dict[str, int]] = []
    for point in trace.points:
        counts: dict[str, int] = {}
        if point.verdict == 'OK':
            for number, name in call_lines.items():
                count = point.lines.get(f'{source_name}:{number}', 0)
                if count:
                    counts[name] = counts.get(name, 0) + count
        per_point.append(counts)
    used = sorted({name for counts in per_point for name in counts})
    if not used:
        return
    growing: dict[str, bool] = {}
    for name in used:
        series = [(point.n, counts.get(name, 0))
                  for point, counts in zip(trace.points, per_point) if counts.get(name, 0)]
        growing[name] = len(series) >= 2 and series[-1][1] > max(2.0, 2.0 * series[0][1])
    for point, counts in zip(trace.points, per_point):
        for name, calls in counts.items():
            order = LIBRARY_ALGORITHMS[name]
            if growing[name]:
                cost = float(calls)
            elif order == 'n log n':
                cost = calls * point.n * math.log2(max(2, point.n))
            else:
                cost = float(calls * point.n)
            point.library_work += cost
            point.work += cost
            point.opaque_calls[name] = point.opaque_calls.get(name, 0) + calls
    trace.notes.append(
        '标准库排序/堆算法在预编译库里，轨迹看不到它们内部的工作；'
        '报告按输入规模对这类调用折算了理论代价，因此这类报告的置信度最高为中')


# A C source never mentions these; a C++ source almost always mentions one of
# them. This only picks which compiler to try first — if that compiler rejects
# the source the other one is tried, so a wrong guess costs one compile and
# never changes the result.
_CPP_MARKERS = re.compile(
    r'\bstd\s*::'
    r'|#\s*include\s*<(iostream|vector|string|algorithm|map|set|unordered_map'
    r'|unordered_set|queue|stack|deque|bitset|array|tuple|utility|functional'
    r'|memory|numeric|list|sstream|fstream|iomanip|iterator|complex|bits/stdc\+\+\.h|c\w+)>'
    r'|\busing\s+namespace\b'
    r'|\b(template\s*<|nullptr|cout|cin|cerr|endl|class\s+\w+\s*[:{]|public\s*:|virtual\b|constexpr\b)'
)


def collect(source: str, rungs: list[probe.Rung], *, deadline: float,
            seed: int = 0) -> schema.LadderTrace:
    """Run the counted ladder for one C or C++ submission."""
    preferred = _detect_language(source)
    trace = schema.LadderTrace(language=preferred, adapter=NAME, work_unit=WORK_UNIT)
    workdir = (Path(judge_config.work_root())
               / f'cxnat-{seed}-{os.getpid()}-{int(time.time() * 1000)}')
    workdir.mkdir(parents=True, exist_ok=True)
    total_work = 0.0
    try:
        language, build, with_memwatch = _build_measurement(workdir, source, preferred)
        trace.language = language
        if not build.ok:
            detail = _diagnostic(build.diagnostics, workdir)
            trace.points.append(schema.TracePoint(n=rungs[0].n if rungs else 1,
                                                  verdict='COMPILATION_ERROR', detail=detail))
            trace.stop_reason = 'COMPILATION_ERROR'
            return trace
        _require('gcov')
        if language == 'cpp' and not with_memwatch:
            trace.notes.append('学生代码自定义了内存分配函数，测量构建没有链接峰值分配计数器，'
                              '空间类别不采集')
        baseline_dir = _build_baseline(workdir, language)
        for rung in rungs:
            remaining_ms = int((deadline - time.monotonic()) * 1000)
            if remaining_ms < 500:
                trace.stop_reason = 'BUDGET_EXHAUSTED'
                break
            point = _measure_work(workdir, rung, remaining_ms, language)
            trace.points.append(point)
            if point.verdict != 'OK':
                trace.stop_reason = point.verdict
                break
            total_work += point.work
            baseline_work = _measure_baseline(baseline_dir, rung, remaining_ms)
            point.baseline_work = baseline_work
            if total_work >= WORK_BUDGET and len(trace.ok_points) >= 4:
                break
        _apply_library_costs(trace, source, SOURCE_NAME[language])
        if len(trace.ok_points) < 4:
            if trace.stop_reason == 'OK':
                trace.stop_reason = 'BUDGET_EXHAUSTED'
            trace.notes.append(f'只完成 {len(trace.ok_points)} 个档位，档位数不足')
        else:
            _check_determinism(trace, workdir, language, rungs, deadline)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    return trace


def _detect_language(source: str) -> str:
    """Guess the compiler to try first; the successful build decides the label."""
    return 'cpp' if _CPP_MARKERS.search(source) else 'c'


def _require(compiler: str) -> None:
    if shutil.which(compiler) is None:
        raise RuntimeError(f'这台机器上没有可用的 {compiler}，无法对 C/C++ 程序做执行轨迹计数')


def _build_command(language: str, source_name: str, with_memwatch: bool) -> list[str]:
    command = [GCC[language], '-O0', f'-std={STANDARD[language]}',
               '-fprofile-arcs', '-ftest-coverage', '-o', 'main', source_name]
    if language == 'cpp' and with_memwatch:
        command.append(MEMWATCH_NAME)
    return command


def _write_source(directory: Path, source: str, language: str) -> str:
    source_name = SOURCE_NAME[language]
    (directory / source_name).write_text(source, encoding='utf-8')
    return source_name


def _build_measurement(workdir: Path, source: str,
                       preferred: str) -> tuple[str, execution.CompileResult, bool]:
    """Compile the instrumented build, falling back to the other compiler.

    Returns ``(language, result, with_memwatch)``. A source that both compilers
    reject is a real compilation error, and the likely compiler's diagnostics are
    the ones reported. A student program that defines its own ``operator new``
    clashes with the peak-allocation counter; the build is retried without it so
    the program can still be measured (space is then not collected).
    """
    first: execution.CompileResult | None = None
    for index, language in enumerate((preferred, 'c' if preferred == 'cpp' else 'cpp')):
        _require(GCC[language])
        if language == 'cpp' and not MEMWATCH_PATH.exists():
            raise RuntimeError(f'缺少内存计数源文件 {MEMWATCH_PATH}')
        if language == 'cpp':
            shutil.copyfile(MEMWATCH_PATH, workdir / MEMWATCH_NAME)
        source_name = _write_source(workdir, source, language)
        with_memwatch = language == 'cpp'
        result = execution.compile_program(_build_command(language, source_name, with_memwatch),
                                           workdir, COMPILE_TIMEOUT_MS)
        if result.ok:
            return language, result, with_memwatch
        if with_memwatch and _diagnostics_look_like_operator_new_clash(result.diagnostics):
            result = execution.compile_program(_build_command(language, source_name, False),
                                               workdir, COMPILE_TIMEOUT_MS)
            if result.ok:
                return language, result, False
        if index == 0:
            first = result
    return preferred, first or execution.CompileResult(False, '编译失败'), False


def _diagnostics_look_like_operator_new_clash(message: str | None) -> bool:
    text = (message or '').lower()
    return 'duplicate symbol' in text or 'operator new' in text or 'multiple definition' in text


def _build_baseline(workdir: Path, language: str) -> Path | None:
    """Compile the minimal reader with the same coverage flags, once."""
    baseline_dir = workdir / 'baseline'
    baseline_dir.mkdir(exist_ok=True)
    source_name = _write_source(baseline_dir, BASELINE_SOURCE[language], language)
    build = execution.compile_program(_build_command(language, source_name, False),
                                      baseline_dir, COMPILE_TIMEOUT_MS)
    return baseline_dir if build.ok else None


def _measure_work(workdir: Path, rung: probe.Rung, remaining_ms: int,
                  language: str) -> schema.TracePoint:
    """Run one rung, then read the coverage counters it produced."""
    _clear_artifacts(workdir)
    memory_path = workdir / f'mem-{rung.n}.json'
    if memory_path.exists():
        memory_path.unlink()
    env = None
    if language == 'cpp':
        env = dict(os.environ)
        env[MEM_ENV] = str(memory_path)
    timeout_ms = min(RUNG_WALL_LIMIT_MS, max(500, remaining_ms))
    outcome = execution.run(['./main'], workdir, rung.input_text.encode('utf-8'), timeout_ms,
                            env=env)
    if outcome.timed_out:
        return schema.TracePoint(n=rung.n, verdict='TIME_LIMIT_EXCEEDED',
                                 detail=f'{timeout_ms} ms 内未结束')
    if outcome.returncode != 0:
        return schema.TracePoint(n=rung.n, verdict='RUNTIME_ERROR',
                                 detail=f'程序退出码 {outcome.returncode}')
    if not _run_gcov(workdir):
        return schema.TracePoint(n=rung.n, verdict='RUNTIME_ERROR',
                                 detail='覆盖率数据无法汇总（gcov 失败）')
    total = _gcov_total(workdir)
    if total <= 0:
        return schema.TracePoint(n=rung.n, verdict='RUNTIME_ERROR',
                                 detail='轨迹中没有记录到任何工作量')
    point = schema.TracePoint(n=rung.n, work=float(total),
                              lines=_source_lines(workdir, SOURCE_NAME[language]))
    point.peak_bytes = _read_peak(memory_path) if language == 'cpp' else None
    return point


def _measure_baseline(baseline_dir: Path | None, rung: probe.Rung,
                      remaining_ms: int) -> float:
    """Counted lines of the minimal reader on the same input; 0 when unavailable."""
    if baseline_dir is None:
        return 0.0
    _clear_artifacts(baseline_dir)
    outcome = execution.run(['./main'], baseline_dir, rung.input_text.encode('utf-8'),
                            min(RUNG_WALL_LIMIT_MS, max(500, remaining_ms)))
    if outcome.timed_out or outcome.returncode != 0:
        return 0.0
    if not _run_gcov(baseline_dir):
        return 0.0
    return float(_gcov_total(baseline_dir))


def _clear_artifacts(directory: Path) -> None:
    """Drop one run's data; ``.gcno`` describes the build and is kept."""
    for pattern in ('*.gcda', '*.gcov'):
        for path in directory.glob(pattern):
            try:
                path.unlink()
            except OSError:
                pass


def _gcno(directory: Path) -> Path | None:
    exact = directory / GCNO_NAME
    if exact.exists():
        return exact
    candidates = [path for path in sorted(directory.glob(GCNO_GLOB))
                  if path.name != f'main-{Path(MEMWATCH_NAME).stem}.gcno']
    return candidates[0] if candidates else None


def _run_gcov(directory: Path) -> bool:
    """Turn one run's ``.gcda`` into ``*.gcov`` text files next to it."""
    graph = _gcno(directory)
    if graph is None:
        return False
    try:
        completed = subprocess.run(['gcov', graph.name], cwd=str(directory),
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   timeout=GCOV_TIMEOUT_MS / 1000.0)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return completed.returncode == 0


def _count_of(field: str) -> int | None:
    """Parse a gcov count field: an integer, or ``-``/``#####``/``=====``.

    An unexecuted block is printed as ``#####`` and an unexecuted exception
    handler line as ``=====``; both are zero. A trailing ``*`` marks a line whose
    blocks were not all executed — the count itself is still the number of times
    the line ran.
    """
    text = field.strip().rstrip('*').strip()
    if not text.isdigit():
        return None
    return int(text)


def _gcov_total(directory: Path) -> int:
    """Sum the numeric execution counts of every ``*.gcov`` in ``directory``."""
    total = 0
    for path in directory.glob('*.gcov'):
        try:
            stream = path.open('r', encoding='utf-8', errors='replace')
        except OSError:
            continue
        with stream:
            for line in stream:
                field, separator, _ = line.partition(':')
                if not separator:
                    continue
                count = _count_of(field)
                if count:
                    total += count
    return total


def _source_lines(directory: Path, source_name: str) -> dict[str, int]:
    """Per-line counts of the student source file, keyed ``<file>:<line>``.

    Only the submission's own file is kept as evidence; the instrumented library
    headers are huge and their line numbers would be meaningless to a student.
    """
    path = directory / f'{source_name}.gcov'
    counts: dict[str, int] = {}
    try:
        lines = path.read_text(encoding='utf-8', errors='replace').splitlines()
    except OSError:
        return counts
    for line in lines:
        parts = line.split(':', 2)
        if len(parts) < 3:
            continue
        count = _count_of(parts[0])
        if not count:
            continue
        try:
            number = int(parts[1])
        except ValueError:
            continue
        if number <= 0:
            continue
        key = f'{source_name}:{number}'
        counts[key] = counts.get(key, 0) + count
    return counts


def _read_peak(path: Path) -> int | None:
    try:
        payload = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    value = payload.get('peak_new')
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return max(0, int(value))


def _check_determinism(trace: schema.LadderTrace, workdir: Path, language: str,
                       rungs: list[probe.Rung], deadline: float) -> None:
    """Re-run the last completed rung and compare counted work.

    Counted lines are exact, so a deterministic program repeats to the last
    unit. A difference means the work depends on randomness or on values the
    generated input does not fix, and the report says so.
    """
    completed = trace.ok_points
    if not completed:
        return
    last = completed[-1]
    rung = next((candidate for candidate in rungs if candidate.n == last.n), None)
    if rung is None:
        return
    remaining_ms = int((deadline - time.monotonic()) * 1000)
    if remaining_ms < 1000:
        return
    repeat = _measure_work(workdir, rung, min(RUNG_WALL_LIMIT_MS, remaining_ms), language)
    if repeat.verdict != 'OK' or repeat.work <= 0:
        return
    delta = abs(repeat.work - last.work) / max(last.work, 1.0)
    trace.repeat_delta = delta
    trace.deterministic = delta <= DETERMINISM_TOLERANCE


def _diagnostic(message: str | None, workdir: Path) -> str:
    """Shorten compiler output and drop the temporary path it was built in."""
    text = (message or '编译失败').replace(str(workdir), '<工作目录>')
    return text[:DIAGNOSTIC_LIMIT]
