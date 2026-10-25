"""Controlled execution configuration for the single-node judge.

The runtime profile is the stable label students may see; the rest of the values
are operator-controlled and are never accepted from a browser request. Missing
values fall back to explicit development defaults instead of unlimited capacity.
"""
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

MOCK = 'MOCK'
LOCAL = 'LOCAL'
LINUX_SANDBOX = 'LINUX_SANDBOX'
EXECUTION_MODES = (MOCK, LOCAL, LINUX_SANDBOX)
LOCAL_PROFILE = 'local-dev-v1'
MOCK_PROFILE = 'mock-v1'

COMPILE_WALL_MS = 30_000
OUTPUT_LIMIT_BYTES = 4 * 1024 * 1024
COMPILER_MESSAGE_LIMIT = 16 * 1024
HEARTBEAT_SECONDS = 10
LEASE_SECONDS = 120
AUTO_RETRIES_PER_CYCLE = 2
AUTO_RETRY_BACKOFF = (5, 30)


def _int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def execution_mode() -> str:
    value = os.getenv('JUDGE_EXECUTION_MODE', MOCK).strip().upper()
    return value if value in EXECUTION_MODES else MOCK


def runtime_profile(mode: str | None = None) -> str:
    mode = mode or execution_mode()
    if mode == LOCAL:
        return LOCAL_PROFILE
    if mode == LINUX_SANDBOX:
        return os.getenv('JUDGE_LINUX_PROFILE', 'linux-sandbox-v1')
    return MOCK_PROFILE


def service_paused() -> bool:
    """Operator pause: stop claiming new work without discarding accepted jobs."""
    return os.getenv('JUDGE_SERVICE_PAUSED', '').strip().lower() in {'1', 'true', 'yes'}


def driver_available(mode: str | None = None) -> bool:
    """Only MOCK and LOCAL have drivers this round; LINUX_SANDBOX must never be labelled."""
    return (mode or execution_mode()) in (MOCK, LOCAL)


def max_concurrency() -> int:
    return _int('JUDGE_MAX_CONCURRENCY', 2)


def per_student_concurrency() -> int:
    return _int('JUDGE_PER_STUDENT_CONCURRENCY', 3)


def case_wall_limit_ms(cpu_limit_ms: int) -> int:
    """Development wall-clock guard: max(1000ms, 3 x configured CPU limit)."""
    return max(1000, 3 * max(1, cpu_limit_ms))


def work_root() -> Path:
    root = Path(os.getenv('JUDGE_WORK_ROOT', Path(__file__).resolve().parents[3] / '.judge-work'))
    root.mkdir(parents=True, exist_ok=True)
    return root


def lock_root() -> Path:
    root = Path(os.getenv('JUDGE_LOCK_ROOT', work_root() / 'locks'))
    root.mkdir(parents=True, exist_ok=True)
    return root


def python_executable() -> str:
    return sys.executable or 'python3'


@dataclass(frozen=True)
class Toolchain:
    language: str
    label: str
    source_name: str
    compile_command: tuple[str, ...] | None
    run_command: tuple[str, ...]
    available: bool


def _which_all(*names: str) -> bool:
    return all(shutil.which(name) is not None for name in names)


def toolchain(language: str) -> Toolchain | None:
    """Return the controlled adapter for a language, or None when unsupported."""
    if language == 'python3':
        return Toolchain('python3', 'Python 3', 'main.py', None,
                         (python_executable(), '-I', 'main.py'), bool(python_executable()))
    if language in {'cpp', 'c++', 'cpp17', 'g++'}:
        available = _which_all('g++')
        return Toolchain('cpp', 'C++17', 'main.cpp',
                         ('g++', '-O2', '-std=c++17', '-pipe', '-o', 'main', 'main.cpp'),
                         ('./main',), available) if available else None
    if language in {'c', 'c17', 'gcc'}:
        available = _which_all('gcc')
        return Toolchain('c', 'C17', 'main.c',
                         ('gcc', '-O2', '-std=c17', '-pipe', '-o', 'main', 'main.c'),
                         ('./main',), available) if available else None
    if language in {'java', 'java17', 'openjdk'}:
        available = _which_all('javac', 'java')
        return Toolchain('java', 'Java', 'Main.java',
                         ('javac', '-encoding', 'UTF-8', 'Main.java'),
                         ('java', '-cp', '.', 'Main'), available) if available else None
    return None


def supported_languages() -> list[str]:
    return [name for name in ('python3', 'cpp', 'c', 'java') if toolchain(name) is not None]
