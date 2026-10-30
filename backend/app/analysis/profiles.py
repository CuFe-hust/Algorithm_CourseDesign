"""Data-side seed for the per-problem scale ladder.

The family assignment below is not a guess about which algorithm a student
writes: it describes the *input format* of the problem, which is what the
generator needs. A problem whose input the platform cannot synthesise simply has
no profile and produces an UNMEASURABLE report.

The new complexity route counts executed work, so a problem whose answer is
huge (Hanoi moves, permutations, Gray codes, N-queens counts) is still
measurable: the adapter drains and discards the output. Only a problem with a
single fixed input case cannot scale at all, and it is listed in
:data:`NOT_SCALABLE`.
"""
from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analysis import probe
from app.db.models import (AssignmentItem, Problem, ProblemComplexityProfile,
                           ProblemVersion, User)

QUESTION_BANK = Path(__file__).resolve().parents[3] / 'data' / 'formatted' / 'questions.programming.json'

# Acceptance measures the whole ladder with the same tracer students are
# measured with, so the seed's verdict and the shipped report cannot disagree:
# the reference solution has to finish several rungs, every rung it ran has to
# end with verdict OK, and total work has to grow with n. A fixed seed keeps the
# verdict reproducible; the budget caps one problem at a few seconds.
VALIDATION_SEED = 20261028
VALIDATION_BUDGET_MS = 20_000
MIN_COMPLETED_RUNGS = 3
MIN_WORK_GROWTH = 1.5

# code -> (family, spec). ``spec`` only adjusts the generator; it never encodes
# a expected complexity class, because that would bias the report.
PROFILES: dict[str, tuple[str, dict]] = {
    'CODE-P01': ('INT_ARRAY_ROWS', {'max_n': 1000}),
    'CODE-P02': ('SINGLE_INT', {'max_n': 10 ** 7, 'max': 10 ** 7}),
    'CODE-P03': ('INT_ARRAY_ROWS', {'max_n': 1000, 'header_extra': 1000}),
    'CODE-P04': ('INT_ARRAY', {'max_n': 10000}),
    # Interval coverage: "m n" then n intervals "l r" with 1 <= l <= r <= m.
    'CODE-P05': ('INT_ARRAY_ROWS_TWO_HEADER', {'max_n': 100000, 'arity': 2, 'rows_sorted': True}),
    'CODE-P06': ('INT_ARRAY', {'max_n': 1000}),
    # Gas station: "n" then n gas values then n cost values.
    'CODE-P07': ('TWO_INT_ARRAYS', {'max_n': 100000, 'max_value': 10000}),
    'CODE-P08': ('INT_ARRAY', {'max_n': 100000}),
    'CODE-P09': ('INT_ARRAY_ROWS', {'max_n': 20000}),
    'CODE-P10': ('INT_ARRAY', {'kind': 'permutation', 'max_n': 200000}),
    # Fast power: one line "a b p". b is the exponent, so work grows like log b.
    'CODE-P11': ('THREE_INTS', {'max_n': 10 ** 9, 'max_a': 10 ** 9,
                                'max_b': 10 ** 9, 'max_c': 10 ** 9}),
    # Rope cutting: "n k" then n lengths; k is the requested piece count.
    'CODE-P12': ('INT_ARRAY_WITH_K', {'max_n': 100000}),
    'CODE-P13': ('INT_ARRAY_ROWS', {'max_n': 20000}),
    'CODE-P14': ('SINGLE_INT', {'max_n': 10}),
    # Big-integer multiplication: two decimal strings, at most 200 digits each.
    'CODE-P15': ('BIG_TWO_STRINGS', {'max_n': 200}),
    # 0/1 knapsack: "n W" then n "weight value" rows; W stays at the limit so
    # work grows with n instead of with the capacity.
    'CODE-P16': ('KNAPSACK', {'max_n': 1000, 'capacity': 1000}),
    'CODE-P17': ('TWO_STRINGS', {'max_n': 1000}),
    'CODE-P18': ('INT_ARRAY', {'max_n': 100000}),
    'CODE-P19': ('TWO_STRINGS', {'max_n': 1000}),
    # Number triangle: "n" then 1 + 2 + ... + n values.
    'CODE-P20': ('TRIANGLE_ROWS', {'max_n': 1000}),
    # Coin change: "n amount" then n coin values. Both the coin count (<= 100)
    # and the target stay inside the problem's limits.
    'CODE-P21': ('INT_ARRAY_WITH_K', {'max_n': 100}),
    # Matrix-chain: "n" then n + 1 dimensions.
    'CODE-P22': ('INT_ARRAY', {'max_n': 100, 'extra_values': 1}),
    # Stone merging: O(n^3) interval DP, so the ladder stops at 100; a rung of
    # 256 already needs more than the tracer's ten-second per-rung limit.
    'CODE-P23': ('INT_ARRAY', {'max_n': 100}),
    'CODE-P24': ('TWO_STRINGS', {'max_n': 2000}),
    'CODE-P25': ('INT_ARRAY', {'max_n': 100000, 'max_value': 10000}),
    # Single-source shortest path: "n m" then m weighted edges.
    'CODE-P26': ('GRAPH_EDGES', {'max_n': 100000, 'edge_arity': 3, 'edge_factor': 2}),
    # Negative cycle: "n m" then m weighted edges.
    'CODE-P27': ('GRAPH_EDGES', {'max_n': 2000, 'edge_arity': 3, 'edge_factor': 2}),
    # Minimum spanning tree: "n m" then m weighted edges.
    'CODE-P28': ('GRAPH_EDGES', {'max_n': 100000, 'edge_arity': 3, 'edge_factor': 2}),
    # Topological sort: "n m" then m edge pairs, no duplicate edges or self loops.
    'CODE-P29': ('GRAPH_EDGES', {'max_n': 10000, 'edge_arity': 2,
                                 'edge_factor': 2, 'simple': True}),
    'CODE-P30': ('GRID', {'max_n': 300}),
    # Friend circles: "n m", m edges, "q", q pairs.
    'CODE-P31': ('GRAPH_EDGE_QUERIES', {'max_n': 100000}),
    # Lowest common ancestor: "n root", n - 1 tree edges, "q", q pairs.
    'CODE-P32': ('GRAPH_TREE_QUERIES', {'max_n': 100000}),
    # Strongly connected components: "n m" then m edge pairs.
    'CODE-P33': ('GRAPH_EDGES', {'max_n': 10000, 'edge_arity': 2, 'edge_factor': 2}),
    # Bipartite check: "n m" then m edge pairs.
    'CODE-P34': ('GRAPH_EDGES', {'max_n': 100000, 'edge_arity': 2, 'edge_factor': 2}),
    'CODE-P35': ('SINGLE_INT', {'max_n': 8}),
    # N-queens: every rung costs 2^n nodes, so n = 12 alone spends ten seconds
    # of tracing; 10 still separates the factorial class.
    'CODE-P36': ('SINGLE_INT', {'max_n': 10}),
    # A fixed 9x9 sudoku board: every rung would be the same input.
    'CODE-P37': ('FIXED', {'text': '53..7....\n6..195...\n.98....6.\n'
                                  '8...6...3\n4..8.3..1\n7...2...6\n'
                                  '.6....28.\n...419..5\n....8..79\n'}),
    # Graph colouring: "n m k" then m edges u < v, no duplicates.
    # Graph colouring: the reference scans the adjacency matrix, so O(n^3) work;
    # n = 100 costs eleven seconds, 48 keeps the same growth signal.
    'CODE-P38': ('GRAPH_COLORING', {'max_n': 48}),
    'CODE-P39': ('SINGLE_INT', {'max_n': 8}),
    # Word search: "n m", n grid rows, then the word.
    'CODE-P40': ('GRID_WITH_WORD', {'max_n': 6}),
    'CODE-P41': ('TWO_STRINGS', {'max_n': 100000}),
    'CODE-P42': ('ONE_STRING', {'max_n': 100000}),
    # Prefix counting: n words, then q query strings (a prefix of a word each).
    'CODE-P43': ('STRING_LIST', {'max_n': 100000, 'word_length': 8, 'queries': True}),
    'CODE-P44': ('ONE_STRING', {'max_n': 100000, 'alphabet': 'abcdefghijklm'}),
    # Substring hash queries: the string s, then q, then q lines "l1 r1 l2 r2".
    'CODE-P45': ('STRING_RANGE_QUERIES', {'max_n': 100000}),
    # Longest common prefix: "n" then n strings.
    'CODE-P46': ('STRING_LIST', {'max_n': 1000, 'word_length': 100}),
    'CODE-P47': ('INT_ARRAY', {'kind': 'permutation', 'max_n': 100000}),
    # k-th smallest: "n k" then n numbers.
    'CODE-P48': ('INT_ARRAY_WITH_K', {'max_n': 1000000}),
    # Binary search: "n q", a sorted array, then q targets.
    'CODE-P49': ('SORTED_ARRAY_QUERIES', {'max_n': 100000}),
    # Sliding-window maximum: "n k" then n numbers.
    'CODE-P50': ('INT_ARRAY_WITH_K', {'max_n': 1000000}),
    'CODE-P51': ('INT_ARRAY', {'max_n': 100000}),
    'CODE-P52': ('INT_ARRAY', {'max_n': 100000}),
    # Postfix evaluation: one line of numbers and + operators.
    'CODE-P53': ('POSTFIX_EXPRESSION', {'max_n': 2000}),
    # Fenwick tree: "n q", n numbers, then q update/query operation lines.
    'CODE-P54': ('INT_ARRAY_OPERATIONS', {'max_n': 200000}),
    # Two-stack queue: q lines of push x / pop / front.
    'CODE-P55': ('STACK_OPERATIONS', {'max_n': 100000}),
    # Top-k frequent: "n k" then n distinct numbers (a permutation keeps k <= m).
    'CODE-P56': ('INT_ARRAY_WITH_K', {'max_n': 100000, 'kind': 'permutation'}),
    'CODE-P57': ('SINGLE_INT', {'max_n': 10 ** 6, 'max': 10 ** 6}),
    # Extended Euclid: the step count follows log n, so keep a and b on the same
    # scale and away from the n / n + 1 pair, whose gcd stops after two steps.
    'CODE-P58': ('TWO_INTS', {'max_n': 10 ** 9, 'max_a': 10 ** 9, 'max_b': 10 ** 9,
                              'scale_b': 0.618}),
    # Binomial coefficients: "T" then T rows "n m" with 0 <= m <= n.
    'CODE-P59': ('INT_ARRAY_ROWS', {'max_n': 10000, 'row_kind': 'ordered'}),
    # Big-number addition: digit strings, not letters.
    'CODE-P60': ('BIG_TWO_STRINGS', {'max_n': 1000}),
    # Base conversion: n with the base fixed at 2, so the digit count follows
    # log2 n. The base must stay inside 2..16 or the digit table is overrun.
    'CODE-P61': ('TWO_INTS', {'max_n': 4096, 'max_a': 10 ** 18, 'max_b': 2, 'offset_b': 1}),
    'CODE-P62': ('SINGLE_INT', {'max_n': 10 ** 9, 'max': 10 ** 9}),
    'CODE-P63': ('INT_ARRAY', {'max_n': 200000}),
    'CODE-P64': ('INT_ARRAY', {'max_n': 100000}),
    'CODE-P65': ('SINGLE_INT', {'max_n': 16}),
    # Range bitwise AND: l fixed at 1 and r = n + 1, so the shift loop runs
    # once per bit of r instead of once per trailing-1 run of n.
    'CODE-P66': ('TWO_INTS', {'max_n': 4096, 'max_a': 2 * 10 ** 9,
                              'max_b': 2 * 10 ** 9, 'scale_a': 0, 'offset_a': 1}),
    'CODE-P67': ('MATRIX', {'max_n': 100}),
    'CODE-P68': ('MATRIX', {'max_n': 100}),
    # Subarrays with sum k: "n k" then n numbers.
    'CODE-P69': ('INT_ARRAY_WITH_K', {'max_n': 200000, 'max_value': 10000}),
    # Difference array: "n m" then m rows "l r v" with l <= r.
    'CODE-P70': ('INT_ARRAY_ROWS_TWO_HEADER', {'max_n': 200000, 'arity': 3, 'rows_sorted': True}),
}

# Problems whose input cannot be scaled at all: the bank declares a single fixed
# case, so every rung would hand the program the same bytes and the report has
# nothing to compare. Seeding stores EXISTING_CASES with this reason instead of
# a family that would measure nothing.
NOT_SCALABLE: dict[str, str] = {
    'CODE-P37': '固定盘面输入（数独），规模无法伸缩，降级为不可测',
}

DEFAULT_NOT_SCALABLE_REASON = '没有可伸缩的输入格式，降级为不可测'


def _reference_python(bank: dict, code: str) -> str | None:
    solutions = bank.get(code) or []
    for solution in solutions:
        if solution.get('language') == 'Python':
            return solution.get('content')
    return None


def validate_profile(bank: dict, code: str, family: str, spec: dict) -> tuple[bool, str]:
    """Acceptance-test one profile with the bank's own reference solution.

    A matching input format is not enough. A program can parse the header, read
    the data and still return without doing the work -- for example when a
    property of the generated data short-circuits it, or when it only reads a
    size and prints a constant. The old check (one rung, exit code 0) accepted
    those. Acceptance now counts work over the whole ladder, using the same
    tracer students are measured with, and requires three facts:

    1. at least ``MIN_COMPLETED_RUNGS`` rungs finished;
    2. every rung the reference solution ran ended with verdict ``OK`` (a
       non-zero exit, a timeout, a runtime error or an empty trace fails --
       ``TracePoint.verdict`` reports them all);
    3. total work grew: the last rung costs at least ``MIN_WORK_GROWTH`` times
       the first, so "格式对了但程序提前返回" is rejected.

    The growth ratio is a floor for *having* a growth signal, not a fitted
    class; a genuinely constant-work program cannot support a complexity report.
    """
    source = _reference_python(bank, code)
    if source is None:
        return False, '题库没有该题的 Python 参考解，无法验收生成的输入'
    try:
        rungs = probe.ladder(family, VALIDATION_SEED, spec)
    except Exception as error:  # noqa: BLE001 - any generation failure disqualifies
        return False, f'生成伸缩输入失败：{error}'
    if len(rungs) < MIN_COMPLETED_RUNGS:
        return False, f'可执行档位只有 {len(rungs)} 个，少于 {MIN_COMPLETED_RUNGS} 个'
    # Imported here so seeding without validation does not pull the tracer (and
    # the judge configuration it needs) into the import graph.
    from app.analysis.trace import collect as trace_collect
    try:
        trace = trace_collect.collect(source, 'python3', family, spec,
                                      seed=VALIDATION_SEED, budget_ms=VALIDATION_BUDGET_MS)
    except Exception as error:  # noqa: BLE001 - a broken runner means "not accepted"
        return False, f'采集执行轨迹失败：{error}'
    failed = next((point for point in trace.points if point.verdict != 'OK'), None)
    if failed is not None:
        detail = (failed.detail or '没有细节').strip().splitlines()
        return False, (f'参考解在 n={failed.n} 的生成输入上未正常结束'
                       f'（{failed.verdict}：{detail[-1][:120] if detail else "没有细节"}）')
    finished = trace.ok_points
    if len(finished) < MIN_COMPLETED_RUNGS:
        return False, (f'参考解只完成 {len(finished)} 个档位'
                       f'（需要 {MIN_COMPLETED_RUNGS} 个）：{trace.stop_reason}')
    first, last = finished[0], finished[-1]
    growth = last.work / max(first.work, 1.0)
    if growth < MIN_WORK_GROWTH:
        return False, (f'工作量没有随 n 增长：n={first.n} 为 {first.work:.0f}，'
                       f'n={last.n} 为 {last.work:.0f}，比值 {growth:.2f} '
                       f'小于 {MIN_WORK_GROWTH}')
    return True, ''


def revalidate_profiles(db: Session) -> dict:
    """Re-acceptance-test every seeded measurable profile already stored.

    The first seeding of the hand-written table shipped families that did not fit
    the problem's format for a third of the problems; this pass walks the stored
    rows, downgrades the ones the reference solution can no longer be measured on
    (format mismatch, early return, no work growth) and records why. Manual
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
    the reference solution (format, completed rungs, and work that grows with n)
    before it is stored, and a failure is downgraded to ``EXISTING_CASES``
    (problem reported as unmeasurable) instead of shipping a profile whose
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
        reason = NOT_SCALABLE.get(problem.code)
        if entry is None or reason is not None:
            family, spec = 'EXISTING_CASES', {'reason': reason or DEFAULT_NOT_SCALABLE_REASON}
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
