"""Normalized trace records shared by every language adapter.

An adapter turns one execution of the submission on one generated input into a
:class:`TracePoint`. The numbers are *counts*, never durations:

* ``line_events`` / ``jump_events`` — executed source lines and loop back-edges
  (Python),
* ``work`` — the single work-unit total the inference layer fits,
* ``library_work`` — the part of ``work`` contributed by known-cost library
  calls (``sorted`` and friends), so the report can say how much of the total it
  could not see,
* ``peak_bytes`` — peak allocation, when the language adapter can observe it,
* ``functions`` — per-function call counts and per-call samples. A sample
  carries the size of the function's arguments, the work done inside the frame
  excluding self-recursive children, and the argument sizes of the recursive
  children. This is what :mod:`app.analysis.trace.recurrence` needs.

Samples are capped: a program that runs a function a million times must not turn
a stored report into a megabyte of JSON, and the recurrence only needs a
representative spread across argument sizes.
"""

from __future__ import annotations

from dataclasses import dataclass, field

MAX_SAMPLES_PER_FUNCTION = 240
MAX_FUNCTIONS_IN_PAYLOAD = 24
MAX_LINES_IN_PAYLOAD = 120


@dataclass
class FrameSample:
    """One observed call of a function."""

    args: tuple[int, ...] = ()
    cost: float = 0.0
    children: tuple[tuple[int, ...], ...] = ()

    def to_payload(self) -> dict:
        return {'args': list(self.args), 'cost': round(self.cost, 3),
                'children': [list(child) for child in self.children]}


@dataclass
class FunctionTrace:
    name: str
    calls: int = 0
    callers: dict[str, int] = field(default_factory=dict)
    samples: list[FrameSample] = field(default_factory=list)
    max_depth: int = 0

    def add_sample(self, sample: FrameSample) -> None:
        # Reservoir-free deterministic thinning: keep the first N samples and
        # then every k-th one, so both the shallow and the deep end of the call
        # tree are represented when a function is called very often.
        self.samples.append(sample)
        if len(self.samples) > MAX_SAMPLES_PER_FUNCTION * 2:
            self.samples = self.samples[::2]

    def to_payload(self) -> dict:
        return {
            'name': self.name,
            'calls': self.calls,
            'callers': dict(sorted(self.callers.items())),
            'samples': [sample.to_payload() for sample in self.samples[:MAX_SAMPLES_PER_FUNCTION]],
            'max_depth': self.max_depth,
        }


@dataclass
class TracePoint:
    """Counts recorded for one input size."""

    n: int
    verdict: str = 'OK'
    detail: str | None = None
    work: float = 0.0
    baseline_work: float = 0.0
    line_events: int = 0
    jump_events: int = 0
    library_work: float = 0.0
    max_depth: int = 0
    peak_bytes: int | None = None
    functions: dict[str, FunctionTrace] = field(default_factory=dict)
    lines: dict[str, int] = field(default_factory=dict)
    opaque_calls: dict[str, int] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.verdict == 'OK' and self.work > 0

    def to_payload(self) -> dict:
        top_lines = sorted(self.lines.items(), key=lambda item: item[1], reverse=True)
        return {
            'n': self.n,
            'verdict': self.verdict,
            'detail': self.detail,
            'work': round(self.work, 3),
            'baseline_work': round(self.baseline_work, 3),
            'line_events': self.line_events,
            'jump_events': self.jump_events,
            'library_work': round(self.library_work, 3),
            'max_depth': self.max_depth,
            'peak_bytes': self.peak_bytes,
            'functions': {name: function.to_payload()
                          for name, function in list(self.functions.items())[:MAX_FUNCTIONS_IN_PAYLOAD]},
            'lines': dict(top_lines[:MAX_LINES_IN_PAYLOAD]),
            'opaque_calls': dict(sorted(self.opaque_calls.items())),
        }


@dataclass
class LadderTrace:
    """The whole ladder for one submission."""

    language: str
    adapter: str
    work_unit: str
    points: list[TracePoint] = field(default_factory=list)
    stop_reason: str = 'OK'
    input_family: str | None = None
    deterministic: bool | None = None
    repeat_delta: float | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def ok_points(self) -> list[TracePoint]:
        return [point for point in self.points if point.ok]

    def to_payload(self) -> dict:
        return {
            'adapter': self.adapter,
            'work_unit': self.work_unit,
            'input_family': self.input_family,
            'stop_reason': self.stop_reason,
            'deterministic': self.deterministic,
            'repeat_delta': None if self.repeat_delta is None else round(self.repeat_delta, 4),
            'notes': list(self.notes),
            'points': [point.to_payload() for point in self.points],
        }
