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

import ast
import hashlib
import json
import re
import tempfile
import time
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analysis import probe
from app.db.models import (AssignmentItem, Problem, ProblemComplexityProfile,
                           ProblemVersion, ReferenceSolution, TestCase, TestSuite, User)

QUESTION_BANK = Path(__file__).resolve().parents[3] / 'data' / 'formatted' / 'questions.programming.json'

# Acceptance measures the whole ladder with the same tracer students are
# measured with, so the seed's verdict and the shipped report cannot disagree:
# the reference solution has to finish several rungs and every rung it ran has to
# end with verdict OK. A fixed seed keeps the
# verdict reproducible; the budget caps one problem at a few seconds.
VALIDATION_SEED = 20261028
VALIDATION_BUDGET_MS = 20_000
MIN_COMPLETED_RUNGS = 3
ADAPTIVE_VERSION = '2'
ADAPTIVE_BUDGET_SECONDS = 12
BOUND_INFINITY = 10**30

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

    This legacy seed check verifies execution over several rungs using the same
    tracer students are measured with. Automatically discovered profiles also
    undergo the schema and known-answer checks in validate_adaptive.

    1. at least ``MIN_COMPLETED_RUNGS`` rungs finished;
    2. every rung the reference solution ran ended with verdict ``OK`` (a
       non-zero exit, a timeout, a runtime error or an empty trace fails --
       ``TracePoint.verdict`` reports them all);

    Constant work is valid. Input legality and the ability to distinguish growth
    are separate concerns; an O(1) reference must not disqualify a generator.
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
    return True, ''


def revalidate_profiles(db: Session) -> dict:
    """Re-acceptance-test every seeded measurable profile already stored.

    The first seeding of the hand-written table shipped families that did not fit
    the problem's format for a third of the problems; this pass walks the stored
    rows, downgrades the ones the reference solution can no longer be measured on
    (format mismatch, execution failure) and records why. Manual
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
    the reference solution (format and completed rungs)
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


def _normalise(text: str) -> str:
    # Keep W (a header parameter) distinct from w_i (an item field).
    text = re.sub(r'(?<![A-Za-z0-9_])([A-Z])(?![A-Za-z0-9_])',
                  lambda match: 'upper_' + match[1].lower(), text)
    text = text.lower().replace('≤', '<=').replace('≥', '>=').replace('−', '-')
    text = text.replace('×', '*').replace('\\leq', '<=').replace('\\le', '<=')
    text = re.sub(r'\\+[()]', '', text)
    text = re.sub(r'\^\{([^}]+)\}', r'^\1', text)
    text = re.sub(r'(?<=\d)\s*x\s*(?=\d)', '*', text)
    text = re.sub(r'_\{([^}]+)\}', lambda match: '_' + match[1].replace(',', ''), text)
    text = re.sub(r'len\s*\(\s*([a-z]\w*)\s*\)', r'len_\1', text)
    string_context = bool(re.search(r'字符串|主串|模式串|字母|单词|十进制|数字字符|string', text))
    text = re.sub(r'\|([a-z][\w\[\]]*)\|', lambda match:
                  'len_' + match[1] if string_context and re.fullmatch(r'[stp]\d*|word|text|pattern|upper_[a-z]', match[1])
                  else 'abs_' + _name(match[1]), text)
    return text.replace('`', '').replace('$', '')


_NUMBER = r'-?\d+(?:e[+-]?\d+)?(?:[ \t]*(?:\*\*|\^|\*|\+|-|/)[ \t]*\d+(?:e[+-]?\d+)?)*'
_VARIABLE = r'[a-z][a-z0-9_]*(?:\[[^\]\n]+\])*'


def _integer(expression: str) -> int:
    """Read numeric bounds without evaluating names, calls or arbitrary code."""
    return probe.bound_value(expression)


def _name(variable: str) -> str:
    if variable.startswith('len_'):
        return variable
    if variable.startswith('upper_'):
        return variable.split('[')[0]
    return re.sub(r'_[ij0-9]+$|\[.*', '', variable.strip())


def _comparisons(text: str) -> list[tuple[str, bool, str]]:
    """Read supported comparison chains, including lists and reversed bounds."""
    operand = rf'(?:{_NUMBER}|{_VARIABLE}(?:[ \t]*,[ \t]*{_VARIABLE})*)'
    pattern = rf'(?<![a-z0-9_+*/^\-])(?=({operand})\s*(<=|>=|<|>)\s*({operand})(?![a-z0-9_])(?!(?:[ \t]*[(*+^/\-])))'
    result = []
    def terms(value):
        if re.fullmatch(_NUMBER, value.strip()): return [str(_integer(value))]
        return [_name(part.strip()) for part in value.split(',')]
    segments = []
    for section in re.split(r'[，；;\n。]', text):
        current = ''
        for part in section.split(','):
            shared_lower = re.search(rf'{_NUMBER}\s*(?:<=|<)\s*{_VARIABLE}(?:\s*,\s*{_VARIABLE})*\s*$', current)
            if current and re.search(r'<=|>=|<|>', current) and not shared_lower:
                segments.append(current)
                current = part
            else:
                current += (',' if current else '') + part
        segments.append(current)
    for segment in segments:
        for match in re.finditer(pattern, segment):
            prefix = segment[:match.start()].rstrip()
            if prefix and prefix[-1] in '*+/^-' and prefix.strip() != '-':
                continue
            left, right = terms(match[1]), terms(match[3])
            if match[2] in ('>', '>='): left, right = right, left
            result.extend((a, match[2] in ('<', '>'), b) for a in left for b in right)
    return list(dict.fromkeys(result))


def _bounds(text: str) -> dict[str, tuple[int, int]]:
    bounds: dict[str, list[int]] = {}
    def update(variable, low=None, high=None):
        current = bounds.setdefault(_name(variable), [-BOUND_INFINITY, BOUND_INFINITY])
        if low is not None:
            current[0] = max(current[0], low)
        if high is not None:
            current[1] = min(current[1], high)
    relations = _comparisons(text)
    for left, strict, right in relations:
        if not re.fullmatch(r'-?\d+', left): update(left)
        if not re.fullmatch(r'-?\d+', right): update(right)
        if re.fullmatch(r'-?\d+', left) and not re.fullmatch(r'-?\d+', right):
            update(right, low=int(left) + strict)
        elif re.fullmatch(r'-?\d+', right) and not re.fullmatch(r'-?\d+', left):
            update(left, high=int(right) - strict)
    # Numeric consequences help identify field domains; layout schemas retain
    # the parameter-dependent relations as well (e.g. r <= the actual n).
    for _ in range(len(relations) + 1):
        previous = dict((key, tuple(value)) for key, value in bounds.items())
        for left, strict, right in relations:
            if left in bounds and right in bounds:
                update(left, high=bounds[right][1] - strict if bounds[right][1] != BOUND_INFINITY else None)
                update(right, low=bounds[left][0] + strict if bounds[left][0] != -BOUND_INFINITY else None)
        if previous == {key: tuple(value) for key, value in bounds.items()}: break
    # A common prose spelling for the length of two strings.
    length = re.search(rf'(?:长度|length)[^\d\n]{{0,15}}({_NUMBER})\s*(?:至|到|~|and)\s*({_NUMBER})', text)
    if length:
        update('len_s', _integer(length[1]), _integer(length[2]))
    for key, value in list(bounds.items()):
        if key.startswith('abs_') and value[1] != BOUND_INFINITY:
            if value[0] > 0:
                raise ValueError('绝对值下界形成了尚未支持的非连续取值域')
            update(key[4:], -value[1], value[1])
            del bounds[key]
    return {key: tuple(value) for key, value in bounds.items()}


def _adaptive_sizes(low: int, high: int, cap: int) -> list[int]:
    first, limit = max(1, low), min(high, cap)
    sizes = []
    while first <= limit:
        sizes.append(first)
        first = max(first + 1, first * 2)
    if len(sizes) < MIN_COMPLETED_RUNGS and limit - max(1, low) >= 2:
        sizes = sorted({max(1, low), (max(1, low) + limit) // 2, limit})
    return sizes


def _header_names(description: str, bounds: dict) -> list[str]:
    first = re.split(r'第二(?:行|[、,，])|接下来|随后|之后|其后|second line|next\b', description)[0]
    return list(dict.fromkeys(_name(match[0]) for match in re.finditer(_VARIABLE, first)
                             if _name(match[0]) in bounds))


def _domain(name: str, bounds: dict, relations: list, parameters: list[str]) -> dict:
    """Keep parameter-dependent bounds, not just their largest possible value."""
    low, high = bounds.get(name, (-BOUND_INFINITY, BOUND_INFINITY))
    minima = [low] if low != -BOUND_INFINITY else []
    maxima = [high] if high != BOUND_INFINITY else []
    for upward, output in ((True, maxima), (False, minima)):
        pending, seen = [(name, 0)], set()
        while pending:
            current, offset = pending.pop()
            if current in seen: continue
            seen.add(current)
            for left, strict, right in relations:
                source, target = (left, right) if upward else (right, left)
                if source != current or target == name: continue
                adjustment = offset + (-int(strict) if upward else int(strict))
                if target in parameters:
                    output.append(target + (f'{adjustment:+d}' if adjustment else ''))
                elif target in bounds:
                    pending.append((target, adjustment))
    for left, _, right in relations:
        if left == 'abs_' + name and right in parameters:
            minima.append('-' + right)
            maxima.append(right)
    if not minima or not maxima:
        raise probe.ProfileError(f'字段 {name} 的上下界不完整')
    return {'name': name, 'min': list(dict.fromkeys(minima)), 'max': list(dict.fromkeys(maxima))}


def _line_relations(relations: list, names: list[str]) -> list:
    return [[left, strict, right] for left, strict, right in relations
            if left in names and right in names and left != right]


def _alphabet(description: str) -> str | None:
    if re.search(r'ascii.*33.*126|可打印\s*ascii.*不包含空格', description):
        return ''.join(chr(code) for code in range(33, 127))
    if re.search(r'小写|lowercase|a\s*(?:至|到|-)\s*z', description): return 'abcdefghijklmnopqrstuvwxyz'
    if re.search(r'二进制字符串|binary string|仅(?:含|包含|由)[^。；;\n]{0,16}0\s*(?:和|与|、|and|或)?\s*1', description): return '01'
    return None


def _unsupported_arithmetic(description: str, family: str) -> bool:
    """Do not silently drop symbolic constraints the schema cannot enforce."""
    rhs = rf'{_VARIABLE}\s*(?:<=|<|>=|>)\s*{_VARIABLE}[ \t]*(?:[+*/^\-]|\()'
    lhs = rf'{_VARIABLE}[ \t]*(?:\*|\+|-|/|\^)[ \t]*(?:{_VARIABLE}|\d+)[ \t]*(?:<=|<|>=|>)'
    matches = list(re.finditer(rhs, description)) + list(re.finditer(lhs, description))
    end = r'(?![a-z0-9_])(?!(?:[ \t]*[+*/^\-]))'
    for match in matches:
        tail = description[match.start():]
        if family == 'GRAPH_EDGES' and (re.match(r'm\s*<=\s*n\s*\(\s*n\s*-\s*1\s*\)\s*/\s*2' + end, tail)
                                       or re.match(r'n\s*-\s*1\s*<=\s*m' + end, tail)):
            continue  # The complete simple-graph capacity/edge floor is known.
        if family in ('GRID', 'GRID_WITH_WORD', 'MATRIX') and (
                re.match(r'len_word\s*<=\s*n\s*\*\s*m' + end, tail) or
                re.match(r'n\s*\*\s*m\s*<=\s*' + _NUMBER + end, tail)):
            continue  # These complete product constraints have layout checks.
        return True
    return False


def _layout_candidate(description: str, bounds: dict, cases: list) -> tuple[dict | None, str]:
    """Recognise composable layouts; family tags reuse the existing DB vocabulary."""
    samples = [text.strip().splitlines() for text, _ in cases if text.strip()]
    lines = max(samples, key=len, default=[])
    if not lines: return None, ''
    lines = [line.strip() for line in lines]
    relations = _comparisons(description)
    alphabet = _alphabet(description)
    length_bounds = [value for key, value in bounds.items() if key.startswith('len_')]
    family, layout, distributions, limits = None, [], ['random'], []
    scale, low, high, cap = '', 1, 4096, 4096

    def field(name, parameters=(), value=None):
        result = _domain(name, bounds, relations, list(parameters))
        if value is not None: result['value'] = value
        return result

    def header(names, values):
        return {'kind': 'ints', 'fields': [field(name, names, value) for name, value in zip(names, values)],
                'relations': _line_relations(relations, names)}

    def text_node(length, minimum, maximum, characters, **extra):
        return dict(kind='text', length=length, min=minimum, max=maximum, alphabet=characters, **extra)

    def finite_range(name):
        interval = bounds.get(name)
        if interval is None or any(abs(value) == BOUND_INFINITY for value in interval):
            raise probe.ProfileError(f'参数 {name} 的范围不完整')
        return interval

    # Digit strings must be recognised before treating the samples as integers.
    if len(lines) == 2 and all(line.isascii() and line.isdigit() for line in lines) and re.search(
            r'十进制|数字字符|ascii\s*数字', description):
        if not length_bounds:
            match = re.search(rf'(?:位数|长度)[^\d\n]{{0,12}}({_NUMBER})\s*(?:到|至|\.\.)\s*({_NUMBER})', description)
            if match: length_bounds = [(_integer(match[1]), _integer(match[2]))]
        if not length_bounds: return None, '十进制字符串缺少长度范围'
        low = max(1, max(value[0] for value in length_bounds))
        high = min(value[1] for value in length_bounds)
        layout = [text_node('_scale', low, high, '0123456789', no_leading_zero=True) for _ in range(2)]
        family, distributions = 'BIG_TWO_STRINGS', ['random', 'identical']
        scale = 'n 为两个十进制整数的位数；生成无多余前导零的表示'
    elif alphabet and length_bounds and len(lines) >= 3 and set(lines[0]) <= set(alphabet) \
            and lines[1].isdigit() and len(lines) == int(lines[1]) + 2 and re.search(r'每行.*四个整数|每行.*4\s*个整数', description) \
            and re.search(r'区间|substring', description):
        if 'q' not in bounds: return None, '字符串区间查询的次数范围不明确'
        q_low, q_high = finite_range('q')
        low, high = max(1, q_low, max(item[0] for item in length_bounds)), min(q_high, min(item[1] for item in length_bounds))
        query_fields = [dict(name=name, min=1, max='_string_length') for name in ('l1', 'r1', 'l2', 'r2')]
        layout = [text_node('_scale', low, high, alphabet, bind_length='_string_length'),
                  header(['q'], ['_scale']), {'kind': 'repeat', 'count': 'q', 'body': [
                      {'kind': 'ints', 'fields': query_fields, 'relations': [['l1', False, 'r1'], ['l2', False, 'r2']]}]}]
        family, distributions, scale = 'STRING_RANGE_QUERIES', ['random', 'repeated'], 'n 为字符串长度与区间查询数；区间端点始终位于当前字符串内'
    else:
        try: head = list(map(int, lines[0].split()))
        except ValueError: head = []
        names = _header_names(description, bounds)[:len(head)]
        if head and len(names) != len(head): return None, ''
        if len(lines) == 1 and len(head) in (2, 3):
            intervals = [finite_range(name) for name in names]
            values = ['_scale', '_scale*618//1000+1'] + ([head[2]] if len(head) == 3 else [])
            if any(left == names[0] and right == names[1] for left, _, right in relations):
                values = [intervals[0][0], '_scale'] + values[2:]
                low, high = max(1, intervals[1][0], intervals[0][0] + 1), intervals[1][1]
                scale = f'n 为参数 {names[1]} 的数值；{names[0]} 固定为 {intervals[0][0]}'
            elif intervals[1][1] <= 1024 and intervals[0][1] > 1024:
                values[1] = head[1]
                low, high = max(1, intervals[0][0]), intervals[0][1]
                scale = f'n 为参数 {names[0]} 的数值；{names[1]} 固定为 {head[1]}'
            else:
                low, high = max(1, intervals[0][0], intervals[1][0]), min(intervals[0][1], intervals[1][1])
                scale = 'n 为前两个整数的共同数值尺度；两者按不同固定比例增长'
            if len(head) == 3: scale += f'；第三参数固定为 {head[2]}'
            layout, family, cap = [header(names, values)], 'TWO_INTS' if len(head) == 2 else 'THREE_INTS', 1048576
        elif len(head) in (1, 2):
            n_name = names[0]
            low, high = finite_range(n_name)
            low = max(1, low)
            body = lines[1:]
            mentioned = [_name(match[0]) for match in re.finditer(_VARIABLE, description)]
            mentioned = [name[4:] if name.startswith('abs_') else name for name in mentioned]
            fields = list(dict.fromkeys(name for name in mentioned if name in bounds and name not in names
                        and name not in ('i', 'j') and not name.startswith('len_')))
            numeric_body = []
            try: numeric_body = [list(map(int, line.split())) for line in body]
            except ValueError: pass
            # Character grids and word lists contain an integer header, so their
            # layout must be selected before the standalone-string fallback.
            if len(head) == 2 and len(body) == head[0] and numeric_body and all(len(row) == head[1] for row in numeric_body) \
                    and re.search(r'矩阵|matrix', description):
                if len(fields) != 1: return None, '矩阵元素范围不明确'
                m_name = names[1]
                m_low, m_high = finite_range(m_name)
                low, high = max(low, m_low), min(high, m_high)
                layout = [header(names, ['_scale', '_scale']), {'kind': 'repeat', 'count': n_name,
                    'body': [dict(field(fields[0], names), kind='array', count=m_name)]}]
                product = re.search(rf'{n_name}\s*\*\s*{m_name}\s*<=\s*({_NUMBER})', description)
                if product:
                    layout[0]['relations'].append([f'{n_name}*{m_name}', False, str(_integer(product[1]))])
                    high = min(high, int(_integer(product[1]) ** 0.5))
                family, cap, scale = 'MATRIX', 128, 'n 为矩阵边长；行数与列数同时取 n（不是元素总数）'
            elif len(head) == 2 and len(body) in (head[0], head[0] + 1) and (
                    re.search(r'网格|迷宫|grid|(?:每行|各含|各行).*字符', description)):
                m_name = names[1]
                m_low, m_high = finite_range(m_name)
                low, high = max(low, m_low), min(high, m_high)
                characters = '.#' if '.' in description and '#' in description else alphabet
                if characters is None: return None, '网格字符集未明确或尚未支持'
                node = text_node(m_name, m_low, m_high, characters, exact=True)
                if characters == '.#' and re.search(r'起点|终点|左上角|右下角', description):
                    node.update(grid_endpoints=True, grid_rows=n_name)
                layout = [header(names, ['_scale', '_scale']),
                          {'kind': 'repeat', 'count': n_name, 'body': [node]}]
                if len(body) == head[0] + 1:
                    if alphabet is None: return None, '网格后单词的字符集不明确'
                    word_bounds = bounds.get('len_word', (1, BOUND_INFINITY))
                    if word_bounds[1] == BOUND_INFINITY:
                        if not re.search(rf'len_word\s*<=\s*{n_name}\s*\*\s*{m_name}', description):
                            return None, '网格后单词的长度范围不明确'
                        word_bounds = (word_bounds[0], finite_range(n_name)[1] * m_high)
                    low, high = max(low, word_bounds[0]), min(high, word_bounds[1])
                    layout.append(text_node('_scale', max(1, word_bounds[0]),
                        [word_bounds[1], f'{n_name}*{m_name}'], alphabet))
                    family, distributions = 'GRID_WITH_WORD', ['random', 'repeated']
                else: family = 'GRID'
                product = re.search(rf'{n_name}\s*\*\s*{m_name}\s*<=\s*({_NUMBER})', description)
                if product:
                    layout[0]['relations'].append([f'{n_name}*{m_name}', False, str(_integer(product[1]))])
                    high = min(high, int(_integer(product[1]) ** 0.5))
                cap, scale = 128, 'n 为网格边长；行数与列数同时取 n' + ('，单词长度同时取 n' if family == 'GRID_WITH_WORD' else '')
            elif len(head) == 1 and len(body) >= head[0] and not numeric_body and alphabet:
                word_count = head[0]
                if not all(line and set(line) <= set(alphabet) for line in body[:word_count]): return None, ''
                total = re.search(rf'(?:总长度|长度之和)[^。；;\n]{{0,12}}(?:不超过|<=)\s*({_NUMBER})', description)
                total_max = _integer(total[1]) if total else None
                word_min = max(1, max((value[0] for value in length_bounds), default=1))
                word_max = min((value[1] for value in length_bounds), default=total_max or BOUND_INFINITY)
                if word_max == BOUND_INFINITY: return None, '字符串列表缺少长度上界或总长度上界'
                if total_max: high = min(high, total_max // word_min)
                word_length = min(max(8, word_min), word_max, total_max // min(high, cap) if total_max else word_max)
                word = text_node(word_length, word_min, word_max, alphabet, tag='words')
                layout = [header(names, ['_scale']), {'kind': 'repeat', 'count': n_name, 'body': [word]}]
                if total_max: limits.append({'tag': 'words', 'max': total_max})
                if len(body) > word_count:
                    q_line = body[word_count].split()
                    if len(q_line) != 1 or not q_line[0].isdigit() or len(body) != word_count + int(q_line[0]) + 1:
                        return None, '字符串列表之后的查询布局不明确'
                    if 'q' not in bounds: return None, '字符串查询次数范围不明确'
                    q_low, q_high = finite_range('q')
                    low, high = max(low, q_low), min(high, q_high)
                    layout += [header(['q'], ['_scale']), {'kind': 'repeat', 'count': 'q', 'body': [dict(word, tag='queries')]}]
                    if total_max: limits.append({'tag': 'queries', 'max': total_max})
                    scale = 'n 为单词数与查询数；每个单词长度固定，分别按总长度约束裁剪'
                elif len(body) != word_count: return None, ''
                else: scale = 'n 为字符串个数；单个字符串长度固定，生成长度总和受约束'
                family, distributions = 'STRING_LIST', ['random', 'identical']
            elif numeric_body:
                graph_count = head[0] - 1 if 'root' in names else head[1] if len(head) == 2 else -1
                if len(head) == 2 and graph_count >= 0 and len(body) > graph_count and re.search(r'查询|询问', description) \
                        and re.search(r'树|朋友|无向|undirected', description) \
                        and len(numeric_body[graph_count]) == 1 and len(body) == graph_count + 1 + numeric_body[graph_count][0] \
                        and all(len(row) == 2 for row in numeric_body[:graph_count] + numeric_body[graph_count+1:]):
                    if 'q' not in bounds: return None, '图查询的次数上界不明确'
                    q_low, q_high = finite_range('q')
                    low, high = max(low, q_low), min(high, q_high)
                    tree = 'root' in names
                    if tree:
                        root_low, _ = finite_range('root')
                        low = max(low, root_low)
                        values, edge_count = ['_scale', max(1, root_low)], n_name + '-1'
                    else:
                        edge_low, edge_high = finite_range(names[1])
                        low, high = max(low, edge_low * 2), min(high, edge_high * 2 + 1)
                        values, edge_count = ['_scale', '_scale//2'], names[1]
                    options = dict(adaptive_graph=True, directed=False, tree=tree, connected=tree,
                                   edge_arity=2, simple=tree, min_edges=0, max_edges=10**18)
                    query_fields = [dict(name=name, min=1, max=n_name) for name in ('_query_u', '_query_v')]
                    layout = [header(names, values), {'kind': 'edges', 'vertices': n_name, 'count': edge_count, 'options': options},
                              header(['q'], ['_scale']), {'kind': 'repeat', 'count': 'q',
                                  'body': [{'kind': 'ints', 'fields': query_fields}]}]
                    family = 'GRAPH_TREE_QUERIES' if tree else 'GRAPH_EDGE_QUERIES'
                    scale = 'n 为节点数与查询次数；树严格生成 n-1 条连通无环边' if tree else 'n 为人数与查询次数；关系数约为 n/2'
                elif len(head) == 1 and len(body) == head[0] and all(len(row) == i + 1 for i, row in enumerate(numeric_body)) \
                        and re.search(r'第\s*i\s*行.*i\s*个|三角', description):
                    if len(fields) != 1: return None, '三角形元素范围不明确'
                    element = field(fields[0], names)
                    layout = [header(names, ['_scale']), {'kind': 'repeat', 'count': n_name,
                        'body': [dict(element, kind='array', count='_row+1')]}]
                    family, cap, scale = 'TRIANGLE_ROWS', 128, 'n 为三角形层数，元素总数为 n(n+1)/2'
                elif len(head) == 1 and len(body) == 2 and all(len(row) == head[0] for row in numeric_body) \
                        and re.search(r'第三行|第二[、,，]三行|两个.*数组|two arrays', description):
                    if len(fields) != 2: return None, '两个数组的独立取值范围不能确认'
                    arrays = [dict(field(name, names), kind='array', count=n_name) for name in fields]
                    for node, name in zip(arrays, fields):
                        explicit_sum = re.search(rf'sum\({name}(?:\[.*?\])?\)\s*<=\s*({_NUMBER})', description)
                        common_sum = re.search(rf'所有.*(?:总和|之和).*?(?:不超过|<=)\s*({_NUMBER})', description)
                        if explicit_sum or common_sum:
                            node['sum_max'] = _integer((explicit_sum or common_sum)[1])
                    layout = [header(names, ['_scale']), *arrays]
                    family, scale = 'TWO_INT_ARRAYS', 'n 为两个数组各自的长度；分别检查元素范围与声明的和上限'
                elif len(body) == 1 and len(numeric_body[0]) == head[0] and not re.search(r'矩阵|方阵|matrix', description):
                    if re.search(r'不同元素.*个数|不同元素.*数量', description):
                        return None, '参数依赖数组的实际不同元素数，当前布局尚未支持该约束'
                    if len(fields) != 1: return None, '数组元素范围与其他输入字段无法区分'
                    values = ['_scale']
                    if len(head) == 2:
                        dependent = any(left == names[1] and right == names[0] for left, _, right in relations)
                        values.append('_scale//2+1' if dependent else head[1])
                    array = dict(field(fields[0], names), kind='array', count=n_name)
                    if re.search(r'互不相同|互异|不重复|distinct|unique|严格递增|严格递减', description): array['unique'] = True
                    if re.search(r'非递增|非升序|降序|严格递减|descending', description): array['order'] = 'descending'
                    elif re.search(r'非递减|非降序|升序|严格递增|ascending', description): array['order'] = 'ascending'
                    if '有序' in re.sub(r'不保证.*?有序|不要求.*?有序', '', description) and not array.get('order'):
                        return None, '有序数组的排序方向不明确'
                    total = re.search(rf'(?:总和|元素之和)[^。；;\n]{{0,12}}(?:不超过|<=)\s*({_NUMBER})', description)
                    explicit = re.search(rf'sum\({fields[0]}\)\s*<=\s*({_NUMBER})', description)
                    if total or explicit: array['sum_max'] = _integer((total or explicit)[1])
                    if array.get('unique'):
                        value_low, value_high = bounds[fields[0]]
                        high = min(high, value_high - value_low + 1)
                    layout = [header(names, values), array]
                    family = 'INT_ARRAY' if len(head) == 1 else 'INT_ARRAY_WITH_K'
                    scale = 'n 为数组长度' + (f'；参数 {names[1]} ' + ('随 n 增长' if dependent else f'固定为 {head[1]}') if len(head) == 2 else '')
                    distributions = [array['order']] if array.get('order') else ['random', 'ascending', 'descending']
                elif len(head) == 1 and len(body) == head[0] and re.search(
                        r'(?:每行|第\s*i\s*行|接下来).*?(?:两个|一个|两|一|2\s*个|1\s*个).*整数', description) \
                        and fields and len(fields) == len(numeric_body[0]) and all(len(row) == len(fields) for row in numeric_body):
                    layout = [header(names, ['_scale']), {'kind': 'repeat', 'count': n_name, 'body': [
                        {'kind': 'ints', 'fields': [field(name, names) for name in fields],
                         'relations': _line_relations(relations, names + fields)}]}]
                    family, scale = 'INT_ARRAY_ROWS', 'n 为记录条数；各条记录分别满足字段范围与大小关系'
                elif len(head) == 1 and len(body) == head[0] and all(len(row) == head[0] for row in numeric_body) \
                        and re.search(r'方阵|矩阵|matrix', description):
                    if len(fields) != 1: return None, '矩阵元素的范围不能确认'
                    layout = [header(names, ['_scale']), {'kind': 'repeat', 'count': n_name,
                        'body': [dict(field(fields[0], names), kind='array', count=n_name)]}]
                    family, cap, scale = 'MATRIX', 128, 'n 为方阵边长，输入只包含一个维度参数'
                elif len(head) == 2 and len(body) == head[1] + 1 and len(numeric_body[0]) == head[0] \
                        and all(len(row) == 1 for row in numeric_body[1:]) and re.search(r'查询|询问|quer', description):
                    if not fields:
                        shared_range = re.search(rf'(?:数组|元素|查询值).*?在\s*({_NUMBER})\s*(?:\.\.|到|至|~)\s*({_NUMBER})', description)
                        if shared_range:
                            interval = (_integer(shared_range[1]), _integer(shared_range[2]))
                            bounds = dict(bounds, _array_value=interval, _query_value=interval)
                            fields = ['_array_value', '_query_value']
                    if len(fields) != 2: return None, '数组和查询值的独立范围不能确认'
                    q_name = names[1]
                    q_low, q_high = finite_range(q_name)
                    low, high = max(low, q_low), min(high, q_high)
                    array = dict(field(fields[0], names), kind='array', count=n_name)
                    if re.search(r'非降序|非递减|升序|non.decreasing', description): array['order'] = 'ascending'
                    layout = [header(names, ['_scale', '_scale']), array,
                        {'kind': 'repeat', 'count': q_name, 'body': [{'kind': 'ints', 'fields': [field(fields[1], names)]}]}]
                    family = 'SORTED_ARRAY_QUERIES' if array.get('order') else 'INT_ARRAY_QUERIES'
                    scale = 'n 为数组长度与查询次数；两者同时增长'
                elif len(head) == 1 and len(body) == 1 and len(numeric_body[0]) == head[0] + 1 \
                        and re.search(rf'{n_name}\s*\+\s*1\s*个', description):
                    if len(fields) != 1: return None, '额外数组元素的范围不明确'
                    layout = [header(names, ['_scale']), dict(field(fields[0], names), kind='array', count=n_name + '+1')]
                    family, scale = 'INT_ARRAY', 'n 为首行参数；后续数组严格包含 n+1 个元素'
                elif len(head) == 2 and len(body) in head and all(len(row) in (1, 2, 3) for row in numeric_body) \
                        and re.search(r'(?:接下来|随后|之后)\s*(?:' + '|'.join(names) + r')\s*行', description) \
                        and not re.search(r'有向|无向|图|树|自环|重边|矩阵|方阵|graph|tree|matrix', description):
                    declaration = re.search(r'(?:接下来|随后|之后)\s*(' + '|'.join(names) + r')\s*行', description)
                    row_count = declaration[1]
                    if len(body) != head[names.index(row_count)]:
                        return None, '记录行数与输入说明中的计数参数不一致'
                    if not re.search(r'行|记录|rows', description) or len(fields) != len(numeric_body[0]): return None, ''
                    if any(len(row) != len(fields) for row in numeric_body): return None, ''
                    values = ['_scale' if name == row_count else head[index] for index, name in enumerate(names)]
                    # If row values are bounded by the other header, both counts
                    # grow together; independent capacities stay fixed.
                    other = next(name for name in names if name != row_count)
                    if any(left in fields and right == other for left, _, right in relations):
                        values = ['_scale', '_scale']
                        other_low, other_high = finite_range(other)
                        low, high = max(low, other_low), min(high, other_high)
                    else:
                        low, high = finite_range(row_count)
                    record_fields = [field(name, names) for name in fields]
                    capacity = next((name for name in names if name in ('upper_w', 'capacity')), None)
                    if capacity and re.search(r'背包|容量', description):
                        fixed_capacity = head[names.index(capacity)]
                        weights = [item for item in record_fields if item['name'] in ('w', 'weight')
                                   and bounds[item['name']][0] <= fixed_capacity]
                        if weights:
                            for item in weights: item['capacity_parameter'] = capacity
                            distributions = ['random', 'within_capacity']
                    layout = [header(names, values), {'kind': 'repeat', 'count': row_count, 'body': [
                        {'kind': 'ints', 'fields': record_fields,
                         'relations': _line_relations(relations, names + fields)}]}]
                    family = 'INT_ARRAY_ROWS_TWO_HEADER'
                    scale = 'n 为记录数；与记录字段相关的头部参数共同增长，其余头部参数固定为样例值'
        if family is None: return None, ''
    if _unsupported_arithmetic(description, family):
        return None, '含有当前布局无法完整校验的参数算术约束'
    sizes = _adaptive_sizes(max(1, low), high, cap)
    if len(sizes) < MIN_COMPLETED_RUNGS: return None, '组合输入布局缺少至少三个合法规模'
    scale = re.sub(r'upper_([a-z])\b', lambda match: match[1].upper(), scale)
    spec = {'layout': layout, 'min_n': max(1, low), 'max_n': high, 'sizes': sizes,
            'distributions': distributions, 'scale': scale, 'length_limits': limits}
    if family in ('INT_ARRAY', 'INT_ARRAY_WITH_K') and len(layout) == 2 and layout[1]['kind'] == 'array':
        element_bounds = bounds.get(layout[1]['name'])
        if element_bounds: spec.update(value_min=element_bounds[0], value_max=element_bounds[1])
        if layout[1].get('order'): spec['order'] = layout[1]['order']
    try:
        for text, _ in cases: probe.validate_input(family, text, spec)
        for size in sizes:
            text = probe.generate(family, size, VALIDATION_SEED, spec)
            probe.validate_input(family, text, spec, size=size)
    except (ValueError, KeyError, IndexError, SyntaxError) as error:
        return None, f'组合输入结构与声明约束不一致：{error}'
    return {'family': family, 'spec': spec}, ''


def adaptive_candidates(version, cases: list[tuple[str, str]]) -> tuple[list[dict], str]:
    """Infer explicit, supported input schemas without consulting problem codes.

    Samples establish layout, not semantics. Numeric/character constraints must
    also be present in the input specification or data constraints. Ambiguous or
    unsupported formats are left unsupported rather than selected by exit code.
    """
    description = _normalise((version.input_spec_md or '') + '\n' + (version.data_constraints_md or ''))
    single = re.sub(r'没有多组(?:测试|数据|输入|询问)*|无多组数据|只有一组数据|只有一组|单组数据|single test case', '', description)
    if re.search(r'多组|多测试|直到.*(?:结束|eof)|until.*eof|交互|interactive', single):
        return [], '暂不自动推断多组、EOF 或交互式输入'
    if re.search(r'元素.*(?:质数|素数)|(?:必须|保证|为|是).{0,12}(?:质数|素数)|每个.*出现.*次|保证.*回文|二分图|强连通|不重合|两两不同|'
                 r'元素.*(?:必须为偶数|必须为奇数)|(?:数组|所有元素|两数组).*(?:和必须相等|和.*必须等于)|'
                 rf'{_VARIABLE}\s*(?:为|是|必须为)\s*(?:奇数|偶数)|'
                 r'(?:总和|元素和|元素之和).{0,12}(?:等于|恰为|==)|sum\([^)]*\)\s*(?:==|=|\+)(?!=)', description):
        return [], '输入包含尚未支持的语义约束'
    if not version.input_spec_md or not cases:
        return [], '需要明确的输入说明和至少一个带答案的测试用例'
    try:
        bounds = _bounds(description)
    except (ValueError, SyntaxError, OverflowError):
        return [], '数据边界表达式暂不能可靠解析'
    try:
        composed, reason = _layout_candidate(description, bounds, cases)
    except (ValueError, KeyError, IndexError, SyntaxError) as error:
        return [], f'组合输入约束暂不能可靠解析：{error}'
    if composed is not None:
        return [composed], ''
    if reason:
        return [], reason
    sample = max((text.strip().splitlines() for text, _ in cases if text.strip()), key=len, default=[])
    if not sample:
        return [], '没有可识别的非空输入'
    sample = [line.strip() for line in sample]
    candidate = None
    spec = {}
    if re.search(r'字符串|string|主串|模式串', description):
        alphabet = _alphabet(description)
        if alphabet is None:
            return [], '字符串的字符集不明确或暂未支持'
        lengths = [value for key, value in bounds.items() if key.startswith('len_')]
        if not lengths:
            return [], '字符串长度范围不明确'
        low, high = max(1, max(value[0] for value in lengths)), min(value[1] for value in lengths)
        header = len(sample) == 2 and sample[0].isdigit() and int(sample[0]) == len(sample[1])
        count = len(sample) - int(header)
        if count not in (1, 2) or header and count != 1:
            return [], '字符串之外还有未识别的输入字段'
        candidate = 'ONE_STRING' if count == 1 else 'TWO_STRINGS'
        spec.update(alphabet=alphabet, length_header=header,
                    distributions=['random', 'repeated'] if count == 1 else ['random', 'identical'],
                    scale='n 为字符串长度；两字符串同时取长度 n' if count == 2 else 'n 为字符串长度')
    else:
        try:
            rows = [list(map(int, line.split())) for line in sample]
        except ValueError:
            return [], '样例不是已支持的整数或字符串格式'
        head = rows[0]
        first_clause = re.split(r'第二行|接下来|随后|之后|其后|second line|next\b', description)[0]
        names = _header_names(description, bounds)
        if not head or not names or names[0] not in bounds:
            return [], '无法确定首行的规模参数及其范围'
        scale_name = names[0]
        low, high = bounds[scale_name]
        low = max(0, low)
        if high == BOUND_INFINITY:
            return [], '缺少规模参数的有限上界'
        spec['scale'] = f'n 表示输入参数 {scale_name}'
        if len(head) == 1 and len(rows) == 1:
            candidate = 'SINGLE_INT'
            spec.update(min=low, max=high)
        elif len(head) == 2 and re.search(r'图|graph|树|tree|有向|无向|先后关系', description):
            if len(rows) != head[1] + 1 or not rows[1:] or any(len(row) not in (2, 3) for row in rows[1:]):
                return [], '边列表的格式不能确认'
            directed = not bool(re.search(r'无向|undirected|无根树', description))
            if directed and not re.search(r'有向|directed|先后关系', description):
                return [], '图的方向不明确'
            tree = bool(re.search(r'一棵.*树|(?:是|为)树|\ba tree\b', description))
            connectivity = re.sub(r'不保证.*?连通|not necessarily connected', '', description)
            connected = tree or bool(re.search(r'连通|connected', connectivity))
            arity = len(rows[1])
            if any(len(row) != arity for row in rows[1:]):
                return [], '边的字段数不一致'
            weight = bounds.get('w')
            if arity == 3 and (weight is None or abs(weight[0]) == BOUND_INFINITY or weight[1] == BOUND_INFINITY):
                return [], '边权范围不明确'
            edge_bound = bounds.get(names[1], (0, 10**18)) if len(names) > 1 else (0, 10**18)
            spec.update(adaptive_graph=True, directed=directed, connected=connected, tree=tree,
                        acyclic=bool(re.search(r'无环|acyclic', description)), edge_arity=arity,
                        simple=bool(re.search(r'简单图|simple graph|无自环|不含重边|无重边', description)),
                        min_edges=max(0, edge_bound[0]), max_edges=edge_bound[1], edge_factor=2,
                        weight_min=weight[0] if weight else 1, weight_max=weight[1] if weight else 100,
                        scale='n 为顶点数；生成稀疏简单图，边数随顶点数增长')
            if spec['acyclic'] and not directed and not tree:
                return [], '暂不自动生成无向森林等特殊图结构'
            candidate = 'GRAPH_EDGES'
        elif len(head) == 2 and re.search(r'矩阵|matrix|每行\s*m\s*个', description):
            if len(names) < 2 or names[1] not in bounds:
                return [], '矩阵列数范围不明确'
            low, high = max(low, bounds[names[1]][0]), min(high, bounds[names[1]][1])
            candidate = 'MATRIX'
            spec['scale'] = 'n 为边长；矩阵行数、列数同时取 n（不是元素总数）'
        elif len(head) == 1 and len(rows) == head[0] + 1 and re.search(r'(?:每行|各含|各行).*(?:两个|2\s*个|two).*整数', description):
            fields = [key for key in bounds if key not in names and not key.startswith('len_')]
            if len(fields) != 2 or any(len(row) != 2 for row in rows[1:]):
                return [], '记录字段的数量或范围不明确'
            left, right = (bounds[key] for key in fields)
            ordered = bool(re.search(rf'{fields[0]}_i\s*<\s*{fields[1]}_i', description))
            if ordered:
                left, right = (left[0], min(left[1], right[1] - 1)), (max(right[0], left[0] + 1), right[1])
            if any(abs(value) == BOUND_INFINITY for pair in (left, right) for value in pair):
                return [], '记录字段的取值边界不完整'
            candidate = 'INT_ARRAY_ROWS'
            spec.update(row_bounds=[list(left), list(right)], ordered_rows=ordered)
        elif len(head) in (1, 2) and len(rows) == 2 and len(rows[1]) == head[0]:
            candidate = 'INT_ARRAY' if len(head) == 1 else 'INT_ARRAY_WITH_K'
            if len(head) == 2:
                if len(names) < 2:
                    return [], '第二个输入参数含义不明确'
                parameter = names[1]
                if re.search(rf'\b{parameter}\s*<=\s*{scale_name}\b', description):
                    spec['k_min'] = max(1, bounds.get(parameter, (1, high))[0])
                    low = max(low, spec['k_min'])
                else:
                    parameter_bounds = bounds.get(parameter)
                    if parameter_bounds is None or any(abs(value) == BOUND_INFINITY for value in parameter_bounds):
                        return [], '第二个参数的约束不能确认'
                    spec.update(header_value=head[1], header_min=parameter_bounds[0], header_max=parameter_bounds[1])
                    spec['scale'] += f'；{parameter} 固定为 {head[1]}'
        else:
            return [], '输入布局尚未被自动识别器支持'
        if candidate in ('INT_ARRAY', 'INT_ARRAY_WITH_K', 'MATRIX'):
            values = bounds.get('a') or bounds.get('aij')
            if values is None:
                fields = [value for key, value in bounds.items() if key not in names and key not in ('i', 'j')
                          and not key.startswith('len_') and all(abs(item) != BOUND_INFINITY for item in value)]
                values = fields[0] if len(fields) == 1 else None
            if values is None or any(abs(value) == BOUND_INFINITY for value in values):
                return [], '数组或矩阵元素的取值范围不明确'
            spec.update(value_min=values[0], value_max=values[1])
            sum_limit = re.search(rf'(?:总和|元素之和)[^。；;\n]{{0,12}}(?:不超过|<=)\s*({_NUMBER})', description)
            if sum_limit: spec['sum_max'] = _integer(sum_limit[1])
            if candidate != 'MATRIX':
                spec['unique'] = bool(re.search(r'互不相同|互异|不重复|distinct|unique|严格递增|严格递减', description))
                if spec['unique']:
                    high = min(high, values[1] - values[0] + 1)
                if re.search(r'非递增|降序|non.increasing|descending|严格递减', description):
                    spec['order'] = 'descending'
                elif re.search(r'非递减|升序|递增|non.decreasing|ascending', description):
                    spec['order'] = 'ascending'
                if '有序' in re.sub(r'不保证.*?有序|不要求.*?有序', '', description) and not spec.get('order'):
                    return [], '有序数组的排序方向不明确'
                spec['distributions'] = [spec['order']] if spec.get('order') else ['random', 'ascending', 'descending']
    cap = 128 if candidate == 'MATRIX' else 1048576 if candidate == 'SINGLE_INT' else 4096
    sizes = _adaptive_sizes(low, high, cap)
    if candidate == 'GRAPH_EDGES':
        divisor = 1 if spec['directed'] and not spec['acyclic'] else 2
        sizes = [size for size in sizes if size * (size - 1) // divisor >= spec['min_edges']
                 and (not spec['connected'] or size - 1 <= spec['max_edges'])]
    if len(sizes) < MIN_COMPLETED_RUNGS:
        return [], '合法规模范围不足以提供至少三个不同档位，或最小规模超过采集上限'
    spec.update(min_n=low, max_n=high, sizes=sizes)
    if _unsupported_arithmetic(description, candidate):
        return [], '含有当前模板无法完整校验的参数算术约束'
    try:
        for text, _ in cases:
            probe.validate_input(candidate, text, spec)
    except (ValueError, KeyError, IndexError) as error:
        return [], f'推断出的结构或约束与已有测试用例冲突：{error}'
    return [{'family': candidate, 'spec': spec}], ''


def validate_adaptive(candidate: dict, references: list[tuple[str, str]],
                      cases: list[tuple[str, str]], *, deadline: float | None = None) -> tuple[dict | None, str]:
    """Compile a database reference once, check known answers, then probe sizes.

    A timeout at a larger size caps the ladder; it does not make smaller inputs
    invalid. Neither constant work nor early output is used as a rejection rule.
    """
    from app.judge import checker, config, local
    deadline = deadline or time.monotonic() + ADAPTIVE_BUDGET_SECONDS
    aliases = {'python': 'python3', 'c++': 'cpp', 'c++17': 'cpp', 'c': 'c'}
    selected = next(((aliases.get(language.lower(), language.lower()), source)
                     for language, source in sorted(references, key=lambda ref: 'python' not in ref[0].lower())
                     if config.toolchain(aliases.get(language.lower(), language.lower())) is not None), None)
    if selected is None:
        return None, '当前节点没有可执行的教师参考代码，无法验收自动生成方案'
    language, source = selected
    # Authoring also permits explanations containing one fenced reference
    # program (the demo uses this format). Execute only the matching code block.
    blocks = re.findall(r'```([^\n]*)\n([\s\S]*?)```', source)
    matching = [code for label, code in blocks if aliases.get(label.strip().lower(), label.strip().lower()) == language]
    if len(matching) == 1:
        source = matching[0]
    tool = config.toolchain(language)
    family, spec = candidate['family'], dict(candidate['spec'])
    with tempfile.TemporaryDirectory(prefix='cx-profile-', dir=config.work_root()) as directory:
        workdir = Path(directory)
        (workdir / tool.source_name).write_text(source, encoding='utf-8')
        diagnostics = local._compile(tool, workdir, max(1, int((deadline - time.monotonic()) * 1000)))
        if diagnostics:
            return None, '教师参考代码无法编译，自动生成方案未启用'
        def run(text):
            remaining = int((deadline - time.monotonic()) * 1000)
            if remaining <= 0:
                return 'TIME_LIMIT_EXCEEDED', b''
            hint, output, _ = local._run_case(tool.run_command, workdir, text.encode('utf-8'),
                                             min(1000, remaining), None, total_deadline=deadline)
            return hint, output
        for text, expected in cases[:6]:
            hint, output = run(text)
            if hint or not checker.matches(output, expected.encode('utf-8')):
                return None, '教师参考代码未通过已有测试用例，自动生成方案未启用'
        sizes = list(spec['sizes'])
        checked, outputs = [], []
        for distribution in spec.get('distributions', ['random']):
            accepted = []
            current = dict(spec, distribution=distribution)
            for size in sizes:
                try:
                    text = probe.generate(family, size, VALIDATION_SEED, current)
                    probe.validate_input(family, text, current, size=size)
                except (ValueError, KeyError, IndexError) as error:
                    return None, f'生成数据没有通过结构或约束检查：{error}'
                hint, output = run(text)
                if hint == 'TIME_LIMIT_EXCEEDED':
                    break
                if hint:
                    return None, f'参考代码在生成输入上异常结束（n={size}，{hint}）'
                accepted.append(size)
                outputs.append({'n': size, 'distribution': distribution,
                                'sha256': hashlib.sha256(checker.normalize(output)).hexdigest()})
            if len(accepted) < MIN_COMPLETED_RUNGS:
                return None, '预算内参考代码完成的合法规模不足三个'
            sizes = accepted
            checked.append({'distribution': distribution, 'completed_sizes': accepted})
        spec['sizes'] = sizes
        spec['validation'] = {'reference_language': language, 'known_cases': min(6, len(cases)),
                              'scenarios': checked, 'seed': VALIDATION_SEED,
                              'outputs': [output for output in outputs if output['n'] in sizes]}
        return spec, ''


def check_adaptive_submission(source: str, language: str, family: str, spec: dict) -> tuple[dict | None, str]:
    """Check generated-input answers before publishing growth from those inputs.

    This never changes the original judge result. A disagreement may expose an
    incomplete inference or an untested program path and is reported for review.
    """
    from app.judge import checker, config, local
    tool = config.toolchain(language)
    deadline = time.monotonic() + ADAPTIVE_BUDGET_SECONDS
    sizes = list(spec['sizes'])
    expected = {(entry['distribution'], entry['n']): entry['sha256'] for entry in spec['validation']['outputs']}
    with tempfile.TemporaryDirectory(prefix='cx-check-', dir=config.work_root()) as directory:
        workdir = Path(directory)
        (workdir / tool.source_name).write_text(source, encoding='utf-8')
        if local._compile(tool, workdir, max(1, int((deadline - time.monotonic()) * 1000))):
            return None, '提交在生成输入校验阶段无法编译'
        for distribution in spec.get('distributions', ['random']):
            completed = []
            for size in sizes:
                remaining = int((deadline - time.monotonic()) * 1000)
                if remaining <= 0:
                    break
                text = probe.generate(family, size, spec['validation']['seed'], dict(spec, distribution=distribution))
                hint, output, _ = local._run_case(tool.run_command, workdir, text.encode('utf-8'),
                    min(1000, remaining), None, total_deadline=deadline)
                if hint == 'TIME_LIMIT_EXCEEDED':
                    break
                if hint or hashlib.sha256(checker.normalize(output)).hexdigest() != expected[(distribution, size)]:
                    return None, (f'提交在自动生成输入上与参考解不一致或异常结束（n={size}，{distribution}）；'
                                  '请核对生成约束和代码，本次不发布复杂度结论，原评测结果不变')
                completed.append(size)
            if len(completed) < MIN_COMPLETED_RUNGS:
                return None, '提交在预算内通过输出校验的规模不足三个，暂时无法测量增长'
            sizes = completed
    return dict(spec, sizes=sizes), ''


def resolve_adaptive_profile(db: Session, version: ProblemVersion,
                             existing: ProblemComplexityProfile | None) -> ProblemComplexityProfile:
    """Discover/cache one system profile per immutable problem version.

    Program execution happens outside a database transaction. A version lock is
    taken only when publishing the cache; concurrent workers reuse the first
    result. SEEDED denotes system-created data; adaptive provenance lives in spec.
    """
    if existing is not None and (existing.source == 'TEACHER' or
            existing.family != 'EXISTING_CASES' and not (existing.spec or {}).get('adaptive')):
        return existing
    references = [(reference.language or '', reference.content) for reference in db.scalars(
        select(ReferenceSolution).where(ReferenceSolution.problem_version_id == version.id)
        .order_by(ReferenceSolution.id))]
    suite = db.scalar(select(TestSuite).where(TestSuite.problem_version_id == version.id)
                      .order_by(TestSuite.version_no.desc()).limit(1))
    cases = [(case.input_text, case.expected_output) for case in db.scalars(
        select(TestCase).where(TestCase.test_suite_id == suite.id).order_by(TestCase.sort_order).limit(12))] if suite else []
    version_id = version.id
    fingerprint = hashlib.sha256(json.dumps([ADAPTIVE_VERSION, version.input_spec_md,
        version.data_constraints_md, references, cases], ensure_ascii=False).encode()).hexdigest()
    cached = (existing.spec or {}).get('adaptive', {}) if existing is not None else {}
    if cached.get('fingerprint') == fingerprint and cached.get('status') in ('READY', 'UNSUPPORTED'):
        return existing
    candidates, reason = adaptive_candidates(version, cases)
    db.commit()
    family, spec = 'EXISTING_CASES', {}
    deadline = time.monotonic() + ADAPTIVE_BUDGET_SECONDS
    for candidate in candidates:
        accepted, reason = validate_adaptive(candidate, references, cases, deadline=deadline)
        if accepted is not None:
            family, spec = candidate['family'], accepted
            break
    spec['adaptive'] = {'version': ADAPTIVE_VERSION, 'fingerprint': fingerprint,
                        'status': 'READY' if family != 'EXISTING_CASES' else
                                  'VALIDATION_FAILED' if candidates else 'UNSUPPORTED'}
    if family == 'EXISTING_CASES':
        spec['reason'] = reason
    db.scalar(select(ProblemVersion).where(ProblemVersion.id == version_id).with_for_update())
    row = db.scalar(select(ProblemComplexityProfile).where(
        ProblemComplexityProfile.problem_version_id == version_id).execution_options(populate_existing=True))
    if row is None:
        row = ProblemComplexityProfile(problem_version_id=version_id, source='SEEDED',
                                       family=family, spec=spec, version_no=1)
        db.add(row)
    elif row.source != 'TEACHER' and (row.family == 'EXISTING_CASES' or (row.spec or {}).get('adaptive')) \
            and ((row.spec or {}).get('adaptive', {}).get('fingerprint') != fingerprint or
                 (row.spec or {}).get('adaptive', {}).get('status') == 'VALIDATION_FAILED'):
        row.family, row.spec = family, spec
        row.version_no += 1
    db.commit()
    return row
