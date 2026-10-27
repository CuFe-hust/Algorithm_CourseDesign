"""Data-side seed for the per-problem scale ladder.

The family assignment below is not a guess about which algorithm a student
writes: it describes the *input format* of the problem, which is what the
generator needs. A problem whose input the platform cannot synthesise simply has
no profile and produces a static-only report.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (AssignmentItem, Problem, ProblemComplexityProfile,
                           ProblemVersion, User)

# code -> (family, spec). ``spec`` only adjusts the generator; it never encodes
# a expected complexity class, because that would bias the report.
PROFILES: dict[str, tuple[str, dict]] = {
    'CODE-P01': ('INT_ARRAY_ROWS', {'max_n': 20000}),
    'CODE-P02': ('SINGLE_INT', {'max_n': 10 ** 7, 'max': 10 ** 7}),
    'CODE-P03': ('INT_ARRAY_ROWS', {'max_n': 20000}),
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
    'CODE-P29': ('GRAPH_EDGES', {'max_n': 20000}),
    'CODE-P30': ('GRID', {'max_n': 400}),
    'CODE-P31': ('GRAPH_EDGES', {'max_n': 20000}),
    'CODE-P32': ('GRAPH_EDGES', {'max_n': 20000}),
    'CODE-P33': ('GRAPH_EDGES', {'max_n': 20000}),
    'CODE-P34': ('GRAPH_EDGES', {'max_n': 20000}),
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


def seed_profiles(db: Session) -> dict:
    """Insert a profile for every frozen programming version that has none.

    Idempotent: an existing row is never overwritten, so a teacher-side override
    survives re-seeding.
    """
    teacher = db.scalar(select(User).where(User.login_name == 'demo.teacher'))
    rows = db.execute(select(Problem, ProblemVersion).join(
        ProblemVersion, ProblemVersion.problem_id == Problem.id)
        .where(Problem.question_type == 'PROGRAMMING')).all()
    created = 0
    skipped = 0
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
        db.add(ProblemComplexityProfile(problem_version_id=version.id, family=family,
                                        spec=spec, source='SEEDED',
                                        created_by=teacher.id if teacher else None))
        created += 1
    db.commit()
    return {'created': created, 'skipped': skipped, 'families': len(PROFILES)}
