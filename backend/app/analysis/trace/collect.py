"""Adapter registry and the one entry point the service layer calls.

``collect`` plans the input ladder for a problem and dispatches to the adapter
for the submission language. The inference layer stays language neutral: it only
sees the normalized :class:`~app.analysis.trace.schema.LadderTrace`.
"""
from __future__ import annotations

import time

from app.analysis import probe
from app.judge import config as judge_config

from . import schema

# One report may spend at most this long collecting traces. Counting is cheap
# compared with the old wall-clock ladder, so the budget is mostly a guard
# against a pathological program, not a normal cost.
DEFAULT_BUDGET_MS = 60_000


class UnsupportedLanguage(Exception):
    """No trace adapter exists for this language on this node."""

    def __init__(self, language: str):
        super().__init__(language)
        self.language = language


def normalize_language(language: str | None) -> str | None:
    """Return the canonical toolchain language, or ``None`` when unsupported."""
    tool = judge_config.toolchain(language or '')
    return tool.language if tool is not None else None


def adapter_for(language: str | None):
    canonical = normalize_language(language)
    if canonical == 'python3':
        from .adapters import python_adapter
        return python_adapter
    if canonical in ('c', 'cpp'):
        from .adapters import native_adapter
        return native_adapter
    return None


def supports_language(language: str | None) -> bool:
    return adapter_for(language) is not None


def language_label(language: str | None) -> str:
    tool = judge_config.toolchain(language or '')
    return tool.label if tool is not None else (language or '未知语言')


def collect(source: str, language: str, family: str, spec: dict | None, *,
            seed: int = 0, budget_ms: int = DEFAULT_BUDGET_MS) -> schema.LadderTrace:
    """Run the ladder for one submission and return its normalized trace."""
    adapter = adapter_for(language)
    if adapter is None:
        raise UnsupportedLanguage(language or '')
    deadline = time.monotonic() + budget_ms / 1000.0
    rungs = probe.ladder(family, seed, spec or {})
    if not rungs:
        return schema.LadderTrace(language=normalize_language(language) or language,
                                  adapter=adapter.NAME, work_unit=adapter.WORK_UNIT,
                                  stop_reason='NO_LADDER',
                                  input_family=family,
                                  notes=['该题没有可用的规模伸缩输入'])
    trace = adapter.collect(source, rungs, deadline=deadline, seed=seed)
    trace.input_family = family
    return trace
