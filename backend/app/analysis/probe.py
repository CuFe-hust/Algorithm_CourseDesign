"""Generate the size ladder for a problem family, and run one program per rung.

The generator is deterministic: the same profile, the same size and the same
seed always produce byte-identical input, so a stored report can be reproduced
later. Every family produces a *valid* input according to the problem's declared
input format, because an invalid input would only measure the program's error
path.

Execution is delegated to :mod:`app.judge.local` through the shared supervisor,
so the measurement inherits the start gate, process-group cleanup, output cap
and wall-clock guard rather than re-implementing them.
"""
from __future__ import annotations

import os
import random
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

from app.analysis.algorithms import complexity as growth_rules
from app.judge import config as judge_config
from app.judge import local as judge_local

# Rungs from small to large. Small rungs are cheap and expose constant overhead;
# large ones separate growth classes. A profile may override the list.
DEFAULT_SIZES = (128, 256, 512, 1024, 2048, 4096)

FAMILIES = ('SINGLE_INT', 'TWO_INTS', 'INT_ARRAY', 'INT_ARRAY_ROWS', 'GRAPH_EDGES',
            'TWO_STRINGS', 'ONE_STRING', 'GRID', 'MATRIX', 'FIXED', 'EXISTING_CASES')


@dataclass
class Rung:
    n: int
    input_text: str


# A rung is "informative" once its wall time clearly exceeds interpreter
# start-up; below that the growth signal is buried in a constant.
INFORMATIVE_MS = 40.0
# Doubling ladder. It stops once the largest rung takes a few hundred
# milliseconds (enough signal) or the input size cap is reached.
MAX_SIZES = (256, 512, 1024, 2048, 4096, 8192, 16384, 32768, 65536, 131072,
             262144, 524288, 1048576)
MAX_INPUT_BYTES = 12 * 1024 * 1024
TARGET_TOP_MS = 250.0
# Stop the ladder only once this many rungs completed. It is the fitter's own
# publishable floor, not a separate number: the two drifting apart once silently
# disabled measurement for every quadratic program (the ladder stopped at four
# while the fitter demanded five).
MINIMUM_RUNGS_BEFORE_STOPPING = growth_rules.MINIMUM_PUBLISHABLE_RUNGS

# Reference readers per family. They perform exactly the input work every
# submission must do (read, split, convert, print) and nothing else. Measuring
# them on the same rung gives the input-parsing cost, which is a floor no
# submission can go below. Without this, a binary search looks linear simply
# because reading its input is linear.
IO_REFERENCE = {
    'SINGLE_INT': 'import sys\nprint(int(sys.stdin.buffer.read() or 0) % 7)\n',
    'TWO_INTS': 'import sys\na, b = map(int, sys.stdin.buffer.read().split())\nprint((a + b) % 7)\n',
    'INT_ARRAY': ('import sys\ndata = sys.stdin.buffer.read().split()\n'
                  'n = int(data[0]); total = 0\n'
                  'for token in data[1:1 + n]:\n    total += int(token)\n'
                  'print(total % 7)\n'),
    'INT_ARRAY_ROWS': ('import sys\ndata = sys.stdin.buffer.read().split()\n'
                       'n = int(data[0]); total = 0\n'
                       'for token in data[1:]:\n    total += int(token)\n'
                       'print(total % 7)\n'),
    'GRAPH_EDGES': ('import sys\ndata = sys.stdin.buffer.read().split()\n'
                    'total = 0\nfor token in data: total += int(token)\nprint(total % 7)\n'),
    'TWO_STRINGS': ('import sys\ndata = sys.stdin.buffer.read().split()\n'
                    'print((len(data[0]) + len(data[1])) % 7)\n'),
    'ONE_STRING': 'import sys\nprint(len(sys.stdin.buffer.read()) % 7)\n',
    'GRID': ('import sys\ndata = sys.stdin.buffer.read().split()\n'
             'print(sum(len(row) for row in data[2:]) % 7)\n'),
    'MATRIX': ('import sys\ndata = sys.stdin.buffer.read().split()\n'
               'total = 0\nfor token in data: total += int(token)\nprint(total % 7)\n'),
}
# How far above the reference reader a submission must be before the measured
# growth can be attributed to the algorithm rather than to input parsing.
IO_DOMINANCE_RATIO = 2.5
class ProfileError(ValueError):
    """The stored profile cannot produce a valid input for this problem."""


def _ints(rng: random.Random, count: int, low: int, high: int) -> list[int]:
    return [rng.randint(low, high) for _ in range(count)]


def _permutation(rng: random.Random, n: int) -> list[int]:
    values = list(range(1, n + 1))
    rng.shuffle(values)
    return values


def generate(family: str, n: int, seed: int, spec: dict | None = None) -> str:
    """Return one input text for the given family and size ``n``."""
    spec = spec or {}
    rng = random.Random(f'{seed}:{family}:{n}')
    if family == 'SINGLE_INT':
        low = int(spec.get('min', 1))
        high = int(spec.get('max', 10 ** 9))
        return f'{max(low, min(high, n))}\n'
    if family == 'TWO_INTS':
        return f'{max(1, min(int(spec.get("max_a", 10 ** 9)), n))} ' \
               f'{max(1, min(int(spec.get("max_b", 10 ** 9)), n + int(spec.get("offset_b", 1))))}\n'
    if family == 'INT_ARRAY':
        values = _permutation(rng, n) if spec.get('kind') == 'permutation' else _ints(rng, n, 1, max(2, n))
        return f'{n}\n' + ' '.join(map(str, values)) + '\n'
    if family == 'INT_ARRAY_ROWS':
        rows = []
        for _ in range(n):
            start = rng.randint(0, max(1, n))
            rows.append(f'{start} {start + rng.randint(1, max(1, n // 2))}')
        return f'{n}\n' + '\n'.join(rows) + '\n'
    if family == 'GRAPH_EDGES':
        rows = []
        for _ in range(n):
            u = rng.randint(1, n)
            v = rng.randint(1, n)
            rows.append(f'{u} {v} {rng.randint(1, 1000)}')
        return f'{n} {n}\n' + '\n'.join(rows) + '\n'
    if family == 'TWO_STRINGS':
        alphabet = 'abcdefghijklmnopqrstuvwxyz'
        first = ''.join(rng.choice(alphabet) for _ in range(n))
        second = ''.join(rng.choice(alphabet) for _ in range(n))
        return f'{first}\n{second}\n'
    if family == 'ONE_STRING':
        alphabet = spec.get('alphabet', 'abcdefghijklmnopqrstuvwxyz')
        return ''.join(rng.choice(alphabet) for _ in range(n)) + '\n'
    if family == 'GRID':
        rows = []
        for _ in range(n):
            row = ['#'] * n
            for column in range(n):
                row[column] = '.' if rng.random() > 0.2 else '#'
            row[0] = '.'
            row[-1] = '.'
            rows.append(''.join(row))
        return f'{n} {n}\n' + '\n'.join(rows) + '\n'
    if family == 'MATRIX':
        rows = [f'{n} {n}']
        for _ in range(n):
            rows.append(' '.join(str(value) for value in _ints(rng, n, -100, 100)))
        return '\n'.join(rows) + '\n'
    if family == 'FIXED':
        return str(spec.get('text', ''))
    raise ProfileError(f'unsupported family {family}')


def ladder(family: str, seed: int, spec: dict | None = None,
           sizes: tuple[int, ...] | None = None) -> list[Rung]:
    if family not in FAMILIES:
        raise ProfileError(f'unknown family {family!r}')
    if family == 'EXISTING_CASES':
        return []
    chosen = tuple(sizes or DEFAULT_SIZES)
    maximum = int((spec or {}).get('max_n', 0)) or None
    rungs: list[Rung] = []
    for size in chosen:
        if maximum is not None and size > maximum:
            break
        rungs.append(Rung(n=size, input_text=generate(family, size, seed, spec)))
    return rungs


def _peak_rss_kib(usage) -> int | None:
    """Convert one process's ``ru_maxrss`` to KiB.

    ``resource.RUSAGE_CHILDREN`` is a running maximum over every child, so it
    cannot attribute memory to one run. ``os.wait4`` returns the rusage of the
    specific child instead. Linux reports KiB and macOS reports bytes.
    """
    if usage is None:
        return None
    value = int(usage.ru_maxrss)
    if value <= 0:
        return None
    if sys.platform == 'darwin':
        return value // 1024
    return value


@dataclass
class RungOutcome:
    n: int
    walls_ms: list[float]
    peak_rss_kib: int | None
    verdict: str
    detail: str | None = None

    @property
    def median_ms(self) -> float:
        ordered = sorted(self.walls_ms)
        return ordered[len(ordered) // 2] if ordered else 0.0

    reference_ms: float | None = None

    @property
    def io_ratio(self) -> float | None:
        """Submission time divided by the reference reader time on this rung."""
        if not self.reference_ms or self.median_ms <= 0:
            return None
        return self.median_ms / self.reference_ms

    @property
    def io_dominated(self) -> bool:
        """True when input parsing explains most of this rung's time."""
        ratio = self.io_ratio
        return ratio is not None and ratio < IO_DOMINANCE_RATIO

    def to_payload(self) -> dict:
        return {'n': self.n, 'wall_ms': round(self.median_ms, 3),
                'reference_ms': None if self.reference_ms is None else round(self.reference_ms, 3),
                'io_ratio': None if self.io_ratio is None else round(self.io_ratio, 3),
                'peak_rss_kib': self.peak_rss_kib, 'verdict': self.verdict,
                'detail': self.detail, 'repeats': len(self.walls_ms)}


def measurements(outcomes: list[RungOutcome]):
    """Turn raw outcomes into fitted-ready measurements.

    Two corrections are applied, and both are reported rather than hidden:

    * **Start-up floor.** Process launch, interpreter warm-up and module import
      are a constant on every rung. It is estimated as the smallest observed
      median and subtracted, so a fast program does not fit ``O(1)`` simply
      because a constant dominates.
    * **Input parsing floor.** Reading and converting the generated input also
      grows with ``n`` and is work every valid solution must do. Each rung
      carries the measured time of a pure reader on the same input; when the
      submission is not clearly slower than that reader, its growth cannot be
      attributed to the algorithm.

    Returns ``(measurements, floor_ms, io_dominated_count)``.
    """
    from app.analysis.algorithms import complexity
    ok = [outcome for outcome in outcomes if outcome.verdict == 'OK' and outcome.walls_ms]
    floor = min((outcome.median_ms for outcome in ok), default=0.0)
    rows = []
    io_dominated = 0
    for outcome in outcomes:
        if outcome.verdict != 'OK' or not outcome.walls_ms:
            rows.append(complexity.Measurement(n=outcome.n, wall_ms=0.0, adjusted_ms=0.0,
                                               peak_rss_kib=outcome.peak_rss_kib,
                                               verdict=outcome.verdict))
            continue
        if outcome.io_dominated:
            io_dominated += 1
        adjusted = max(0.0, outcome.median_ms - floor)
        rows.append(complexity.Measurement(n=outcome.n, wall_ms=outcome.median_ms,
                                           adjusted_ms=adjusted,
                                           peak_rss_kib=outcome.peak_rss_kib, verdict='OK',
                                           repeats=len(outcome.walls_ms)))
    return rows, floor, io_dominated


def algorithm_points(outcomes: list[RungOutcome], *, minimum_ratio: float = 2.0):
    """Per-rung input-parsing subtraction, used by the complexity service.

    Returns ``(points, accounting)`` with only rungs where the submission is at
    least ``minimum_ratio`` times slower than the pure reader kept for fitting.
    """
    from app.analysis.algorithms import complexity
    raw = [complexity.Measurement(n=outcome.n, wall_ms=outcome.median_ms,
                                  adjusted_ms=outcome.median_ms,
                                  peak_rss_kib=outcome.peak_rss_kib,
                                  verdict=outcome.verdict, repeats=len(outcome.walls_ms))
           for outcome in outcomes]
    reference = {outcome.n: outcome.reference_ms for outcome in outcomes
                 if outcome.reference_ms is not None}
    return complexity.attribute_growth(raw, reference, minimum_ratio=minimum_ratio)


def measure(source: str, language: str, rungs: list[Rung], *, seed: int = 0,
            wall_limit_ms: int = 4000, budget_ms: int = 120_000,
            repeats: int = 2, gate=None) -> list[RungOutcome]:
    """Compile once and run every rung, returning one outcome per rung.

    Each rung runs ``repeats`` times and the median wall time is kept, because
    the first run of an interpreter-heavy program is systematically slower.
    When the budget runs out, remaining rungs are recorded as not executed: the
    ladder is never silently shortened.
    """
    tool = judge_config.toolchain(language)
    if tool is None:
        raise judge_local.ConfigurationError(f'当前节点不支持该提交语言：{language}')
    deadline = time.monotonic() + budget_ms / 1000.0
    workdir = Path(judge_config.work_root()) / f'cx-{seed}-{int(time.time() * 1000)}'
    workdir.mkdir(parents=True, exist_ok=True)
    outcomes: list[RungOutcome] = []
    try:
        (workdir / tool.source_name).write_text(source, encoding='utf-8')
        diagnostics = judge_local._compile(tool, workdir, None)  # noqa: SLF001 - shared contract
        if diagnostics is not None:
            return [RungOutcome(n=rung.n, walls_ms=[], peak_rss_kib=None,
                                verdict='COMPILATION_ERROR', detail=diagnostics[:400])
                    for rung in rungs]
        for rung in rungs:
            walls: list[float] = []
            verdict = 'OK'
            detail = None
            peak: int | None = None
            for _ in range(max(1, repeats)):
                remaining_ms = int((deadline - time.monotonic()) * 1000)
                if remaining_ms < 200:
                    verdict, detail = 'BUDGET_EXHAUSTED', '总预算已用完'
                    break
                limit = min(wall_limit_ms, remaining_ms)
                try:
                    code, output, timed_out, usage = _run_once(tool, workdir, rung.input_text,
                                                               limit, gate)
                except judge_local.InfrastructureError as error:
                    verdict, detail = 'INFRASTRUCTURE', str(error)
                    break
                observed = _peak_rss_kib(usage)
                if observed is not None:
                    peak = observed if peak is None else max(peak, observed)
                if timed_out:
                    verdict, detail = 'TIME_LIMIT_EXCEEDED', f'{limit} ms 内未结束'
                    walls.append(float(limit))
                    break
                if code not in (0, None):
                    verdict, detail = 'RUNTIME_ERROR', f'退出码 {code}'
                    walls.append(float(limit))
                    break
                walls.append(_last_elapsed[0])
                if verdict != 'OK':
                    break
            outcomes.append(RungOutcome(n=rung.n, walls_ms=walls, peak_rss_kib=peak,
                                        verdict=verdict, detail=detail))
            if verdict == 'INFRASTRUCTURE':
                break
        return outcomes
    finally:
        import shutil
        shutil.rmtree(workdir, ignore_errors=True)


_last_elapsed = [0.0]


def _run_once(tool, workdir: Path, input_text: str, limit_ms: int, gate):
    """Run the compiled program once; return ``(code, output, timed_out, rusage)``."""
    spawned = judge_local.spawn(tool.run_command, workdir)
    released = False
    output = bytearray()
    timed_out = False
    usage = None
    started = time.monotonic()
    try:
        if gate is not None and not gate(spawned):
            raise judge_local.InfrastructureError('执行未获放行')
        released = True
        threading.Thread(target=_feed, args=(spawned, input_text.encode('utf-8')),
                         daemon=True).start()
        threading.Thread(target=_drain, args=(spawned, output), daemon=True).start()
        judge_local.release(spawned)
        deadline = started + limit_ms / 1000.0
        while True:
            reaped = _try_reap(spawned, output)
            if reaped is not None:
                spawned.process.returncode, usage = reaped
                break
            if time.monotonic() > deadline:
                timed_out = True
                judge_local.terminate(spawned)
                reaped = _try_reap(spawned, output, block_ms=2000)
                if reaped is not None:
                    spawned.process.returncode, usage = reaped
                break
            time.sleep(0.002)
        _last_elapsed[0] = (time.monotonic() - started) * 1000.0
        return spawned.process.returncode, bytes(output), timed_out, usage
    finally:
        if released and spawned.process.returncode is None:
            judge_local.terminate(spawned)


def _try_reap(spawned, output, block_ms: int = 0):
    """Reap the child with ``os.wait4`` so per-run rusage is available."""
    deadline = time.monotonic() + block_ms / 1000.0
    while True:
        try:
            pid, status, usage = os.wait4(spawned.process.pid, os.WNOHANG)
        except ChildProcessError:
            return spawned.process.returncode, None
        if pid == spawned.process.pid:
            return os.waitstatus_to_exitcode(status), usage
        if time.monotonic() > deadline:
            return None
        time.sleep(0.002)


def _feed(spawned, payload: bytes) -> None:
    try:
        if spawned.process.stdin is not None:
            spawned.process.stdin.write(payload)
            spawned.process.stdin.close()
    except (BrokenPipeError, OSError, ValueError):
        pass


def _drain(spawned, output: bytearray) -> None:
    stream = spawned.process.stdout
    if stream is None:
        return
    try:
        while True:
            chunk = stream.read(65536)
            if not chunk:
                break
            if len(output) < judge_config.OUTPUT_LIMIT_BYTES:
                output.extend(chunk[:judge_config.OUTPUT_LIMIT_BYTES - len(output)])
    except (OSError, ValueError):
        pass


def escalating_measure(source: str, language: str, family: str, spec: dict | None, *,
                       seed: int, wall_limit_ms: int = 8000, budget_ms: int = 150_000,
                       repeats: int = 3, gate=None, max_rungs: int = 13) -> tuple[list[RungOutcome], str]:
    """Compile once, then climb a doubling ladder until growth beats start-up.

    Interpreter start-up is a constant on every rung and can exceed the whole
    computation for a fast program. Rather than fitting noise, each rung runs
    ``repeats`` times, the median is kept, and the ladder keeps doubling until
    the largest median is well above the smallest (signal), the wall limit is
    hit (a real measurement), the input cap is reached, or the budget is spent.
    The returned reason records which stop happened.

    Reasons: ``OK``, ``TIME_LIMIT_EXCEEDED``, ``RUNTIME_ERROR``,
    ``BUDGET_EXHAUSTED``, ``NO_LADDER``, ``FLOOR_REACHED``, ``LADDER_EXHAUSTED``.
    """
    if family in ('EXISTING_CASES', 'FIXED'):
        return [], 'NO_LADDER'
    tool = judge_config.toolchain(language)
    if tool is None:
        raise judge_local.ConfigurationError(f'当前节点不支持该提交语言：{language}')
    workdir = Path(judge_config.work_root()) / f'cx-{seed}-{int(time.time() * 1000)}'
    workdir.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + budget_ms / 1000.0
    outcomes: list[RungOutcome] = []
    try:
        (workdir / tool.source_name).write_text(source, encoding='utf-8')
        diagnostics = judge_local._compile(tool, workdir, None)  # noqa: SLF001 - shared contract
        if diagnostics is not None:
            return ([RungOutcome(n=0, walls_ms=[], peak_rss_kib=None,
                                 verdict='COMPILATION_ERROR', detail=diagnostics[:400])],
                    'COMPILATION_ERROR')
        for index, size in enumerate(MAX_SIZES):
            if index >= max_rungs:
                return outcomes, 'LADDER_EXHAUSTED' if outcomes else 'NO_LADDER'
            if time.monotonic() > deadline:
                return outcomes, 'BUDGET_EXHAUSTED'
            rung = Rung(n=size, input_text=generate(family, size, seed, spec))
            if len(rung.input_text.encode('utf-8')) > MAX_INPUT_BYTES:
                break
            outcome = _run_rung(tool, workdir, rung, wall_limit_ms, repeats, gate,
                                deadline, seed=seed + index)
            outcome.reference_ms = _io_reference_ms(family, language, rung, wall_limit_ms,
                                                    max(1, repeats - 1), deadline)
            outcomes.append(outcome)
            if outcome.verdict in ('COMPILATION_ERROR', 'INFRASTRUCTURE', 'RUNTIME_ERROR'):
                return outcomes, outcome.verdict
            if outcome.verdict == 'TIME_LIMIT_EXCEEDED':
                return outcomes, 'TIME_LIMIT_EXCEEDED'
            if outcome.verdict == 'BUDGET_EXHAUSTED':
                return outcomes, 'BUDGET_EXHAUSTED'
            executed = [row for row in outcomes if row.verdict == 'OK' and row.walls_ms]
            if len(executed) >= MINIMUM_RUNGS_BEFORE_STOPPING:
                smallest = min(row.median_ms for row in executed)
                largest = max(row.median_ms for row in executed)
                if largest >= max(4.0 * smallest, INFORMATIVE_MS) and executed[-1].n >= 8 * executed[0].n:
                    return outcomes, 'OK'
                if largest >= TARGET_TOP_MS:
                    return outcomes, 'OK'
        executed = [row for row in outcomes if row.verdict == 'OK' and row.walls_ms]
        if len(executed) >= MINIMUM_RUNGS_BEFORE_STOPPING \
                and max(row.median_ms for row in executed) >= INFORMATIVE_MS:
            return outcomes, 'LADDER_EXHAUSTED'
        return outcomes, 'FLOOR_REACHED'
    finally:
        import shutil
        shutil.rmtree(workdir, ignore_errors=True)


def _io_reference_ms(family: str, language: str, rung: Rung, wall_limit_ms: int,
                     repeats: int, deadline: float) -> float | None:
    """Measure a pure input-parsing program on the same rung.

    Returns ``None`` when the family has no reference reader or when the
    measurement could not run; a missing reference must never be replaced by a
    guess, so the ratio stays unknown and the report says nothing about I/O.
    """
    source = IO_REFERENCE.get(family)
    if source is None or language not in ('python3', 'python'):
        return None
    tool = judge_config.toolchain(language)
    if tool is None:
        return None
    workdir = Path(judge_config.work_root()) / f'io-{int(time.time() * 1_000_000)}'
    workdir.mkdir(parents=True, exist_ok=True)
    try:
        (workdir / tool.source_name).write_text(source, encoding='utf-8')
        if judge_local._compile(tool, workdir, None) is not None:  # noqa: SLF001
            return None
        walls: list[float] = []
        for _ in range(max(1, repeats)):
            remaining = int((deadline - time.monotonic()) * 1000)
            if remaining < 200:
                break
            try:
                code, _, timed_out, _ = _run_once(tool, workdir, rung.input_text,
                                                  min(wall_limit_ms, remaining), None)
            except judge_local.InfrastructureError:
                return None
            if timed_out or code not in (0, None):
                return None
            walls.append(_last_elapsed[0])
        if not walls:
            return None
        ordered = sorted(walls)
        return ordered[len(ordered) // 2]
    finally:
        import shutil
        shutil.rmtree(workdir, ignore_errors=True)


def _run_rung(tool, workdir: Path, rung: Rung, wall_limit_ms: int, repeats: int,
              gate, deadline: float, *, seed: int) -> RungOutcome:
    walls: list[float] = []
    peak: int | None = None
    verdict = 'OK'
    detail = None
    for _ in range(max(1, repeats)):
        remaining_ms = int((deadline - time.monotonic()) * 1000)
        if remaining_ms < 200:
            verdict, detail = 'BUDGET_EXHAUSTED', '总预算已用完'
            break
        limit = min(wall_limit_ms, remaining_ms)
        try:
            code, output, timed_out, usage = _run_once(tool, workdir, rung.input_text, limit, gate)
        except judge_local.InfrastructureError as error:
            return RungOutcome(n=rung.n, walls_ms=walls, peak_rss_kib=peak,
                               verdict='INFRASTRUCTURE', detail=str(error))
        observed = _peak_rss_kib(usage)
        if observed is not None:
            peak = observed if peak is None else max(peak, observed)
        walls.append(_last_elapsed[0])
        if timed_out:
            verdict, detail = 'TIME_LIMIT_EXCEEDED', f'{limit} ms 内未结束'
            break
        if code not in (0, None):
            verdict, detail = 'RUNTIME_ERROR', f'退出码 {code}'
            break
    del seed
    return RungOutcome(n=rung.n, walls_ms=walls, peak_rss_kib=peak, verdict=verdict, detail=detail)
