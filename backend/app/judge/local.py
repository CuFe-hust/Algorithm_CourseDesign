"""LOCAL development execution adapter.

Runs the student program on this host with a controlled wall clock, bounded
output, an explicit start gate and process-group cleanup. It is real execution
(``is_mock=false``) but it does not provide Linux sandbox isolation and it does
not measure CPU time or memory, so those stay ``NULL``.
"""
from __future__ import annotations

import os
import signal
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

from app.judge import checker, config

ACCEPTED = 'ACCEPTED'
WRONG_ANSWER = 'WRONG_ANSWER'
COMPILATION_ERROR = 'COMPILATION_ERROR'
TIME_LIMIT_EXCEEDED = 'TIME_LIMIT_EXCEEDED'
RUNTIME_ERROR = 'RUNTIME_ERROR'
OUTPUT_LIMIT_EXCEEDED = 'OUTPUT_LIMIT_EXCEEDED'

VERDICTS = (ACCEPTED, WRONG_ANSWER, COMPILATION_ERROR, TIME_LIMIT_EXCEEDED,
            RUNTIME_ERROR, OUTPUT_LIMIT_EXCEEDED)


class ConfigurationError(Exception):
    """The requested language or runtime profile cannot be executed here."""

    def __init__(self, message: str, code: str = 'JUDGE_CONFIGURATION_UNSUPPORTED'):
        super().__init__(message)
        self.code = code


class InfrastructureError(Exception):
    """A failure of the execution facility, never a student verdict."""

    def __init__(self, message: str, code: str = 'JUDGE_FACILITY_FAILURE'):
        super().__init__(message)
        self.code = code


class OwnershipLost(Exception):
    """The caller no longer owns the job, so no program may be started or kept running."""


@dataclass
class CaseInput:
    sort_order: int
    input_text: str
    expected_output: str


@dataclass
class CaseOutcome:
    sort_order: int
    verdict: str


@dataclass
class ExecutionOutcome:
    verdict: str
    passed: int
    executed: int
    total: int
    wall_ms: int
    compiler_message: str | None = None
    cases: list[CaseOutcome] = field(default_factory=list)


@dataclass
class Spawned:
    process: subprocess.Popen
    started_at: float
    pgid: int


Gate = Callable[[Spawned], bool]


def _child_setup():  # pragma: no cover - kept for callers that need a process group only
    os.setsid()


LAUNCHER = str(Path(__file__).with_name('gate_launcher.py'))


def _kill_group(process: subprocess.Popen, pgid: int | None = None) -> None:
    target = pgid or process.pid
    try:
        os.killpg(target, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        try:
            process.kill()
        except ProcessLookupError:
            pass


def _wait_until_stopped(process: subprocess.Popen, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            pid, status = os.waitpid(process.pid, os.WUNTRACED | os.WNOHANG)
        except ChildProcessError:
            return False
        if pid == process.pid:
            if os.WIFSTOPPED(status):
                return True
            if os.WIFEXITED(status) or os.WIFSIGNALED(status):
                return False
        time.sleep(0.002)
    return False


def spawn(command: Iterable[str], cwd: Path) -> Spawned:
    """Start a gated child: the launcher stops before the student program is exec'ed."""
    process = subprocess.Popen([config.python_executable(), '-I', LAUNCHER, '--', *command],
                               cwd=str(cwd), stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, close_fds=True)
    if not _wait_until_stopped(process):
        _kill_group(process)
        process.wait()
        raise InfrastructureError('执行进程未能在登记前进入受控状态')
    return Spawned(process=process, started_at=time.time(), pgid=process.pid)


def release(spawned: Spawned) -> None:
    os.kill(spawned.process.pid, signal.SIGCONT)


def terminate(spawned: Spawned) -> None:
    _kill_group(spawned.process, spawned.pgid)
    try:
        spawned.process.wait(timeout=5)
    except subprocess.TimeoutExpired:  # pragma: no cover - defensive
        _kill_group(spawned.process, spawned.pgid)


def _run_case(command: Iterable[str], cwd: Path, stdin_bytes: bytes, wall_ms: int,
              gate: Gate | None) -> tuple[str, bytes, int]:
    """Return ``(verdict_hint, output, wall_ms)``; verdict_hint is '' when the program ended."""
    spawned = spawn(command, cwd)
    released = False
    output = bytearray()
    overflow = threading.Event()
    finished = threading.Event()

    def reader():
        stream = spawned.process.stdout
        try:
            while not finished.is_set():
                chunk = stream.read(65536)
                if not chunk:
                    break
                if len(output) < config.OUTPUT_LIMIT_BYTES:
                    remaining = config.OUTPUT_LIMIT_BYTES - len(output)
                    output.extend(chunk[:remaining])
                    if len(chunk) > remaining:
                        overflow.set()
                else:
                    overflow.set()
        except (ValueError, OSError):
            pass

    def writer():
        try:
            if spawned.process.stdin is not None:
                spawned.process.stdin.write(stdin_bytes)
                spawned.process.stdin.close()
        except (BrokenPipeError, ValueError, OSError):
            pass

    thread = threading.Thread(target=reader, daemon=True)
    thread.start()
    hint = ''
    try:
        if gate is not None and not gate(spawned):
            hint = 'GATE_REJECTED'
        else:
            released = True
            threading.Thread(target=writer, daemon=True).start()
            release(spawned)
            deadline = time.monotonic() + wall_ms / 1000.0
            while True:
                if spawned.process.poll() is not None:
                    break
                if overflow.is_set():
                    hint = OUTPUT_LIMIT_EXCEEDED
                    break
                if time.monotonic() > deadline:
                    hint = TIME_LIMIT_EXCEEDED
                    break
                time.sleep(0.005)
    finally:
        # Whatever happened (limit, gate refusal or an exception raised by the gate),
        # the child must never be left stopped or alive after this call.
        if hint or not released:
            terminate(spawned)
        else:
            _kill_group(spawned.process, spawned.pgid)
        finished.set()
        thread.join(timeout=5)
        if not thread.is_alive():
            try:
                spawned.process.stdout.close()
            except OSError:
                pass
        try:
            spawned.process.wait(timeout=5)
        except subprocess.TimeoutExpired:  # pragma: no cover - defensive
            _kill_group(spawned.process, spawned.pgid)
    if not hint and spawned.process.returncode not in (0, None):
        hint = RUNTIME_ERROR
    wall_ms_used = int((time.time() - spawned.started_at) * 1000)
    return hint, bytes(output), wall_ms_used


def _sanitize(text: str, workdir: Path) -> str:
    cleaned = text.replace(str(workdir), '<工作目录>')
    home = str(Path.home())
    cleaned = cleaned.replace(home, '<宿主目录>')
    if len(cleaned) > config.COMPILER_MESSAGE_LIMIT:
        cleaned = cleaned[:config.COMPILER_MESSAGE_LIMIT] + '\n…（诊断已截断）'
    return cleaned


def _compile(tool: config.Toolchain, workdir: Path) -> str | None:
    """Return sanitized diagnostics on failure, ``None`` on success."""
    if tool.language == 'python3':
        command = [config.python_executable(), '-I', '-c',
                   'import py_compile; py_compile.compile("main.py", cfile="main.pyc", doraise=True)']
    else:
        command = list(tool.compile_command or ())
    try:
        completed = subprocess.run(command, cwd=str(workdir), capture_output=True,
                                   timeout=config.COMPILE_WALL_MS / 1000.0)
    except subprocess.TimeoutExpired:
        return '编译超过允许时间'
    if completed.returncode != 0:
        message = (completed.stderr or completed.stdout or b'').decode('utf-8', 'replace')
        return _sanitize(message.strip() or '编译失败', workdir) or '编译失败'
    return None


def execute(source: str, language: str, cases: list[CaseInput], cpu_limit_ms: int,
            gate: Gate | None = None) -> ExecutionOutcome:
    tool = config.toolchain(language)
    if tool is None:
        raise ConfigurationError(f'当前节点不支持该提交语言：{language}')
    if not cases:
        raise ConfigurationError('测试集为空，无法执行')
    workdir = Path(tempfile.mkdtemp(prefix='judge-', dir=str(config.work_root())))
    try:
        (workdir / tool.source_name).write_text(source, encoding='utf-8')
        diagnostics = _compile(tool, workdir)
        total = len(cases)
        if diagnostics is not None:
            return ExecutionOutcome(COMPILATION_ERROR, 0, 0, total, 0, diagnostics)
        wall_limit = config.case_wall_limit_ms(cpu_limit_ms)
        outcomes: list[CaseOutcome] = []
        passed = 0
        wall_total = 0
        for case in cases:
            try:
                hint, output, wall = _run_case(tool.run_command, workdir,
                                               case.input_text.encode('utf-8'), wall_limit, gate)
            except InfrastructureError:
                raise
            except OSError as error:
                raise InfrastructureError('无法启动执行进程') from error
            wall_total += wall
            if hint == 'GATE_REJECTED':
                raise OwnershipLost('执行未获放行')
            if hint == OUTPUT_LIMIT_EXCEEDED:
                verdict = OUTPUT_LIMIT_EXCEEDED
            elif hint == TIME_LIMIT_EXCEEDED:
                verdict = TIME_LIMIT_EXCEEDED
            elif hint:
                verdict = RUNTIME_ERROR
            elif checker.matches(output, case.expected_output.encode('utf-8')):
                verdict = ACCEPTED
            else:
                verdict = WRONG_ANSWER
            if verdict == ACCEPTED:
                passed += 1
            outcomes.append(CaseOutcome(case.sort_order, verdict))
        executed = len(outcomes)
        final = ACCEPTED
        for outcome in outcomes:
            if outcome.verdict != ACCEPTED:
                final = outcome.verdict
                break
        return ExecutionOutcome(final, passed, executed, total, wall_total, None, outcomes)
    finally:
        _cleanup(workdir)


def _cleanup(workdir: Path) -> None:
    import shutil
    try:
        shutil.rmtree(workdir, ignore_errors=True)
    except OSError:  # pragma: no cover - defensive
        pass
