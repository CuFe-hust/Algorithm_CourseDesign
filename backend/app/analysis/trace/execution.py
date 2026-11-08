"""Run one measured program under the judge's start gate and process-group guard.

The adapters reuse :mod:`app.judge.local` so a measured run inherits the same
start gate, process-group termination and wall-clock guard as a real verdict.
Two things differ from judging:

* the process environment may carry adapter-specific variables (the allocation
  counter output path),
* output is drained and discarded instead of compared, and the per-process
  resource usage is returned so a caller can read peak memory when the language
  adapter has no exact counter.
"""
from __future__ import annotations

import os
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from app.judge import local as judge_local


@dataclass
class ProcessResult:
    returncode: int | None
    timed_out: bool
    wall_ms: float
    output_bytes: int
    peak_rss_kib: int | None = None


@dataclass
class CompileResult:
    ok: bool
    diagnostics: str | None = None


def run(command: list[str], cwd: Path, input_bytes: bytes, timeout_ms: int,
        *, env: dict | None = None, capture_rss: bool = True) -> ProcessResult:
    """Run ``command`` with ``input_bytes`` on stdin; discard standard output."""
    spawned = judge_local.spawn(command, cwd, env=env)
    released = False
    drained = [0]
    stop = threading.Event()
    started = time.monotonic()
    usage = None
    timed_out = False
    try:
        judge_local.release(spawned)
        released = True
        threading.Thread(target=_feed, args=(spawned, input_bytes), daemon=True).start()
        threading.Thread(target=_drain, args=(spawned, drained, stop), daemon=True).start()
        deadline = started + timeout_ms / 1000.0
        while True:
            reaped = _try_reap(spawned, capture_rss)
            if reaped is not None:
                spawned.process.returncode, usage = reaped
                break
            if time.monotonic() > deadline:
                timed_out = True
                judge_local.terminate(spawned)
                reaped = _try_reap(spawned, capture_rss, block_ms=2000)
                if reaped is not None:
                    spawned.process.returncode, usage = reaped
                break
            time.sleep(0.002)
        return ProcessResult(returncode=spawned.process.returncode, timed_out=timed_out,
                             wall_ms=(time.monotonic() - started) * 1000.0,
                             output_bytes=drained[0],
                             peak_rss_kib=_peak_rss_kib(usage))
    finally:
        stop.set()
        if released and spawned.process.returncode is None:
            judge_local.terminate(spawned)


def _try_reap(spawned, capture_rss: bool, block_ms: int = 0):
    if not capture_rss:
        spawned.process.poll()
        return (spawned.process.returncode, None) if spawned.process.returncode is not None else None
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


def _peak_rss_kib(usage) -> int | None:
    if usage is None:
        return None
    value = int(usage.ru_maxrss)
    if value <= 0:
        return None
    return value // 1024 if os.sys.platform == 'darwin' else value


def _feed(spawned, payload: bytes) -> None:
    try:
        if spawned.process.stdin is not None:
            spawned.process.stdin.write(payload)
            spawned.process.stdin.close()
    except (BrokenPipeError, OSError, ValueError):
        pass


def _drain(spawned, counter: list[int], stop: threading.Event) -> None:
    stream = spawned.process.stdout
    if stream is None:
        return
    try:
        while not stop.is_set():
            chunk = stream.read(65536)
            if not chunk:
                return
            counter[0] += len(chunk)
    except (OSError, ValueError):
        return


def compile_program(command: list[str], cwd: Path, timeout_ms: int,
                    *, env: dict | None = None) -> CompileResult:
    """Compile a measurement build; diagnostics are shortened and path-sanitized."""
    try:
        completed = subprocess.run(command, cwd=str(cwd), capture_output=True, env=env,
                                   timeout=max(1, timeout_ms) / 1000.0)
    except subprocess.TimeoutExpired:
        return CompileResult(False, '编译超过允许时间')
    except OSError as error:
        return CompileResult(False, f'无法启动编译器：{error}')
    if completed.returncode == 0:
        return CompileResult(True)
    message = (completed.stderr or completed.stdout or b'').decode('utf-8', 'replace').strip()
    message = message.replace(str(cwd), '<工作目录>')
    return CompileResult(False, (message or '编译失败')[:800])
