"""Data-side seed for the per-problem scale ladder.

The family assignment below is not a guess about which algorithm a student
writes: it describes the *input format* of the problem, which is what the
generator needs. A problem whose input the platform cannot synthesise simply has
no profile and produces a static-only report.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analysis import probe
from app.db.models import (AssignmentItem, Problem, ProblemComplexityProfile,
                           ProblemVersion, User)

QUESTION_BANK = Path(__file__).resolve().parents[3] / 'data' / 'formatted' / 'questions.programming.json'

# Review measured a 33% mismatch rate in the hand-written family table: the
# generated input did not fit the problem's real format, so every measured rung
# of every student submission died at runtime. Seeding now verifies each profile
# against the bank's own reference solution and downgrades the mismatches.
VALIDATION_SIZE = 256
VALIDATION_TIMEOUT_S = 10

# code -> (family, spec). ``spec`` only adjusts the generator; it never encodes
# a expected complexity class, because that would bias the report.
PROFILES: dict[str, tuple[str, dict]] = {
    'CODE-P01': ('INT_ARRAY_ROWS', {'max_n': 20000}),
    'CODE-P02': ('SINGLE_INT', {'max_n': 10 ** 7, 'max': 10 ** 7}),
    'CODE-P03': ('INT_ARRAY_ROWS', {'max_n': 20000, 'header_extra': 10000}),
    'CODE-P04': ('INT_ARRAY', {'max_n': 100000}),
    'CODE-P05': ('INT_ARRAY_ROWS', {'max_n': 20000}),
    'CODE-P06': ('INT_ARRAY', {'max_n': 100000}),
    'CODE-P07': ('INT_ARRAY', {'max_n': 100000}),
    'CODE-P08': ('INT_ARRAY', {'max_n': 100000}),
    'CODE-P09': ('INT_ARRAY_ROWS', {'max_n': 20000}),
    'CODE-P10': ('INT_ARRAY', {'kind': 'permutation', 'max_n': 200000}),
    'CODE-P11': ('TWO_INTS', {'max_n': 10 ** 9, 'max_a': 10 ** 9, 'max_b': 10 ** 9}),
    'CODE-P12': ('INT_ARRAY', {'max_n': 100000}),
    'CODE-P13': ('INT_ARRAY_ROWS', {'max_n': 20000}),
    'CODE-P14': ('SINGLE_INT', {'max_n': 22}),
    'CODE-P15': ('TWO_STRINGS', {'max_n': 2000}),
    'CODE-P16': ('INT_ARRAY_ROWS', {'max_n': 2000}),
    'CODE-P17': ('TWO_STRINGS', {'max_n': 2000}),
    'CODE-P18': ('INT_ARRAY', {'max_n': 100000}),
    'CODE-P19': ('TWO_STRINGS', {'max_n': 2000}),
    'CODE-P20': ('INT_ARRAY_ROWS', {'max_n': 1000}),
    'CODE-P21': ('INT_ARRAY', {'max_n': 100000}),
    'CODE-P22': ('INT_ARRAY', {'max_n': 2000}),
    'CODE-P23': ('INT_ARRAY', {'max_n': 2000}),
    'CODE-P24': ('TWO_STRINGS', {'max_n': 2000}),
    'CODE-P25': ('INT_ARRAY', {'max_n': 100000}),
    'CODE-P26': ('GRAPH_EDGES', {'max_n': 20000}),
    'CODE-P27': ('GRAPH_EDGES', {'max_n': 20000}),
    'CODE-P28': ('GRAPH_EDGES', {'max_n': 20000}),
    'CODE-P29': ('GRAPH_EDGES', {'max_n': 20000, 'edge_arity': 2}),
    'CODE-P30': ('GRID', {'max_n': 400}),
    'CODE-P31': ('GRAPH_EDGES', {'max_n': 20000, 'edge_arity': 2}),
    'CODE-P32': ('GRAPH_EDGES', {'max_n': 20000, 'edge_arity': 2}),
    'CODE-P33': ('GRAPH_EDGES', {'max_n': 20000, 'edge_arity': 2}),
    'CODE-P34': ('GRAPH_EDGES', {'max_n': 20000, 'edge_arity': 2}),
    'CODE-P35': ('SINGLE_INT', {'max_n': 8}),
    'CODE-P36': ('SINGLE_INT', {'max_n': 10}),
    'CODE-P37': ('FIXED', {'text': '53..7....\n6..195...\n.98....6.\n'
                                  '8...6...3\n4..8.3..1\n7...2...6\n'
                                  '.6....28.\n...419..5\n....8..79\n'}),
    'CODE-P38': ('SINGLE_INT', {'max_n': 20}),
    'CODE-P39': ('SINGLE_INT', {'max_n': 12}),
    'CODE-P40': ('GRID', {'max_n': 200}),
    'CODE-P41': ('TWO_STRINGS', {'max_n': 100000}),
    'CODE-P42': ('ONE_STRING', {'max_n': 100000}),
    'CODE-P43': ('INT_ARRAY_ROWS', {'max_n': 20000}),
    'CODE-P44': ('ONE_STRING', {'max_n': 100000, 'alphabet': 'abcdefghijklm'}),
    'CODE-P45': ('INT_ARRAY_ROWS', {'max_n': 20000}),
    'CODE-P46': ('TWO_STRINGS', {'max_n': 50000}),
    'CODE-P47': ('INT_ARRAY', {'kind': 'permutation', 'max_n': 200000}),
    'CODE-P48': ('INT_ARRAY', {'kind': 'permutation', 'max_n': 200000}),
    'CODE-P49': ('INT_ARRAY', {'max_n': 200000}),
    'CODE-P50': ('INT_ARRAY', {'max_n': 200000}),
    'CODE-P51': ('INT_ARRAY', {'max_n': 200000}),
    'CODE-P52': ('INT_ARRAY', {'max_n': 100000}),
    'CODE-P53': ('INT_ARRAY', {'max_n': 50000}),
    'CODE-P54': ('INT_ARRAY_ROWS', {'max_n': 20000}),
    'CODE-P55': ('INT_ARRAY_ROWS', {'max_n': 20000}),
    'CODE-P56': ('INT_ARRAY', {'max_n': 200000}),
    'CODE-P57': ('SINGLE_INT', {'max_n': 10 ** 7, 'max': 10 ** 7}),
    'CODE-P58': ('TWO_INTS', {'max_n': 10 ** 9}),
    'CODE-P59': ('INT_ARRAY_ROWS', {'max_n': 20000}),
    'CODE-P60': ('TWO_STRINGS', {'max_n': 20000}),
    'CODE-P61': ('TWO_INTS', {'max_n': 10 ** 9, 'max_a': 10 ** 9, 'max_b': 36, 'offset_b': 1}),
    'CODE-P62': ('SINGLE_INT', {'max_n': 10 ** 9, 'max': 10 ** 9}),
    'CODE-P63': ('INT_ARRAY', {'max_n': 200000}),
    'CODE-P64': ('INT_ARRAY', {'max_n': 100000}),
    'CODE-P65': ('SINGLE_INT', {'max_n': 18}),
    'CODE-P66': ('TWO_INTS', {'max_n': 2 * 10 ** 9, 'max_a': 2 * 10 ** 9, 'max_b': 2 * 10 ** 9}),
    'CODE-P67': ('MATRIX', {'max_n': 600}),
    'CODE-P68': ('MATRIX', {'max_n': 600}),
    'CODE-P69': ('INT_ARRAY', {'max_n': 200000}),
    'CODE-P70': ('INT_ARRAY_ROWS', {'max_n': 20000}),
}

# Problems whose answer is far too large to print at scale: the ladder would
# measure formatting instead of the algorithm, so they stay static-only.
TOO_LARGE_OUTPUT = {'CODE-P14', 'CODE-P35', 'CODE-P36', 'CODE-P37', 'CODE-P39', 'CODE-P65', 'CODE-P42'}


def _reference_python(bank: dict, code: str) -> str | None:
    solutions = bank.get(code) or []
    for solution in solutions:
        if solution.get('language') == 'Python':
            return solution.get('content')
    return None


def validate_profile(bank: dict, code: str, family: str, spec: dict) -> tuple[bool, str]:
    """Run the bank's own reference solution on one generated input.

    A mismatched family produces input the program cannot read, and every rung of
    every student submission then dies at runtime; review measured this on a third
    of the hand-written table. The reference solution is the cheapest oracle: it
    is already in the bank next to the problem it solves.
    """
    source = _reference_python(bank, code)
    if source is None:
        return False, '题库没有该题的 Python 参考解，无法验收生成的输入'
    size = min(VALIDATION_SIZE, int(spec.get('max_n', 0) or VALIDATION_SIZE))
    try:
        text = probe.generate(family, max(1, size), 20261028, spec)
    except Exception as error:  # noqa: BLE001 - any generation failure disqualifies
        return False, f'生成输入失败：{error}'
    try:
        finished = subprocess.run([sys.executable, '-c', source], input=text,
                                  capture_output=True, text=True,
                                  timeout=VALIDATION_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return False, f'参考解在 n={size} 的生成输入上超过 {VALIDATION_TIMEOUT_S} 秒'
    if finished.returncode != 0:
        detail = (finished.stderr or finished.stdout or '').strip().splitlines()
        last = detail[-1][:120] if detail else '无输出'
        return False, f'参考解在 n={size} 的生成输入上退出码 {finished.returncode}：{last}'
    return True, ''


def revalidate_profiles(db: Session) -> dict:
    """Re-acceptance-test every seeded measurable profile already stored.

    The first seeding of the hand-written table shipped mismatched families for a
    third of the problems; this pass walks the stored rows, downgrades the ones
    whose generated input the reference solution rejects, and records why. Manual
    (teacher) profiles are left alone.
    """
    bank_entries = json.loads(QUESTION_BANK.read_text(encoding='utf-8'))
    bank = {entry['code']: entry.get('reference_solutions') or [] for entry in bank_entries}
    rows = db.execute(select(Problem, ProblemComplexityProfile).join(
        ProblemVersion, ProblemVersion.id == ProblemComplexityProfile.problem_version_id)
        .join(Problem, Problem.id == ProblemVersion.problem_id)
        .where(ProblemComplexityProfile.source == 'SEEDED',
               ProblemComplexityProfile.family != 'EXISTING_CASES')).all()
    downgraded: list[dict] = []
    kept = 0
    for problem, profile in rows:
        ok, reason = validate_profile(bank, problem.code, profile.family, dict(profile.spec or {}))
        if ok:
            kept += 1
            continue
        downgraded.append({'code': problem.code, 'family': profile.family, 'reason': reason})
        profile.family = 'EXISTING_CASES'
        profile.spec = {'reason': f'伸缩档验收未通过：{reason}'}
        profile.version_no = (profile.version_no or 1) + 1
    db.commit()
    return {'checked': len(rows), 'kept': kept, 'downgraded': downgraded}


def seed_profiles(db: Session, *, validate: bool = False) -> dict:
    """Insert a profile for every frozen programming version that has none.

    Idempotent: an existing row is never overwritten, so a teacher-side override
    survives re-seeding. With ``validate`` the family is acceptance-tested against
    the reference solution before it is stored, and a mismatch is downgraded to
    ``EXISTING_CASES`` (static-only analysis) instead of shipping a profile whose
    every measurement is guaranteed to fail.
    """
    teacher = db.scalar(select(User).where(User.login_name == 'demo.teacher'))
    bank: dict = {}
    if validate:
        entries = json.loads(QUESTION_BANK.read_text(encoding='utf-8'))
        bank = {entry['code']: entry.get('reference_solutions') or [] for entry in entries}
    rows = db.execute(select(Problem, ProblemVersion).join(
        ProblemVersion, ProblemVersion.problem_id == Problem.id)
        .where(Problem.question_type == 'PROGRAMMING')).all()
    created = 0
    skipped = 0
    downgraded: list[dict] = []
    for problem, version in rows:
        existing = db.scalar(select(ProblemComplexityProfile).where(
            ProblemComplexityProfile.problem_version_id == version.id))
        if existing is not None:
            skipped += 1
            continue
        entry = PROFILES.get(problem.code)
        if entry is None or problem.code in TOO_LARGE_OUTPUT:
            family, spec = 'EXISTING_CASES', {'reason': '输出规模过大，不适合测量'}
        else:
            family, spec = entry
            if validate:
                ok, reason = validate_profile(bank, problem.code, family, spec)
                if not ok:
                    downgraded.append({'code': problem.code, 'family': family, 'reason': reason})
                    family, spec = 'EXISTING_CASES', {'reason': f'伸缩档验收未通过：{reason}'}
        db.add(ProblemComplexityProfile(problem_version_id=version.id, family=family,
                                        spec=spec, source='SEEDED',
                                        created_by=teacher.id if teacher else None))
        created += 1
    db.commit()
    return {'created': created, 'skipped': skipped, 'families': len(PROFILES),
            'validated': validate, 'downgraded': downgraded}
