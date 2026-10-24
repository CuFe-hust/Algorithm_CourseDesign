"""Best-candidate ordering shared by the student progress view and, later, teachers.

The ordering is deliberately small and deterministic:

    (-passed_cases, cpu_time_ms ?, memory_kib ?, -submitted_at, -version_no, -submission_id)

Unknown resources sort after known ones but stay ``None`` in the API; they are
never rewritten as zero. LOCAL results (no measurement) therefore fall back to
the most recent submission, which is a valid development candidate rather than a
service failure.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Candidate:
    submission_id: int
    version_no: int
    submitted_at: datetime
    passed_cases: int
    cpu_time_ms: int | None = None
    memory_kib: int | None = None

    def sort_key(self) -> tuple:
        submitted = self.submitted_at.timestamp() if isinstance(self.submitted_at, datetime) else 0.0
        return (-int(self.passed_cases or 0),
                self.cpu_time_ms if self.cpu_time_ms is not None else math.inf,
                self.memory_kib if self.memory_kib is not None else math.inf,
                -submitted,
                -int(self.version_no or 0),
                -int(self.submission_id))


def choose_best(candidates: list[Candidate]) -> Candidate | None:
    if not candidates:
        return None
    return min(candidates, key=lambda candidate: candidate.sort_key())


def rank(candidates: list[Candidate]) -> list[Candidate]:
    return sorted(candidates, key=lambda candidate: candidate.sort_key())
