#!/usr/bin/env python3
"""Reproducible experiments for the similarity detector.

The module drives the real algorithm code, not a re-implementation:
``app.analysis.algorithms.similarity`` is used through its public functions
``sketch`` / ``compare``, so the numbers below are exactly what the teacher page
would show for the same inputs.

The complexity experiments used to live in this script. They measured wall-clock
time and static structure, both of which the platform no longer uses; they are
kept as an archive in ``docs/design/analysis/algorithm-experiments.md`` and the
current trace-based experiments are in ``scripts/experiment_complexity_trace.py``.

Nothing here opens a database connection, reads a roster or touches the
network. The only input is the reference solution bank in
``data/formatted/questions.programming.json``.

Usage (from ``backend/``)::

    ../.venv/bin/python -m scripts.experiment_similarity_complexity
    ../.venv/bin/python -m scripts.experiment_similarity_complexity --output /tmp/experiments.json

The JSON report goes to stdout; the last line is a one-line summary. With
``--output`` the JSON is additionally written to that path (and stdout keeps
only the summary line).
"""
from __future__ import annotations

import argparse
import ast
import builtins
import io
import json
import keyword
import math
import pathlib
import platform
import random
import statistics
import subprocess
import sys
import tempfile
import time
import tokenize

from app.analysis.algorithms import similarity

# Fixed seed: the ladder contents, the mutation choices and the sampling are all
# deterministic. Wall-clock numbers are real measurements and therefore differ
# between runs; that is reported instead of hiding it.
SEED = 20261028
THRESHOLD = 0.5
SCALE_SIZES = (20, 50, 100, 200)
SCALE_SOURCE = 'CODE-P26'
SCALE_REPEATS = 3

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
QUESTION_BANK = REPO_ROOT / 'data' / 'formatted' / 'questions.programming.json'

# Problems used for the "same problem, different algorithm" false-positive test.
# Each entry is (problem code, plain description, implementation). The
# implementation is checked against the problem's own tests before it is used,
# so it really solves the same task by a different route.
ALTERNATIVE_IMPLEMENTATIONS = {
    'CODE-P01': ('区间 DP 求最长不重叠活动链', '''import sys


def main():
    rows = sys.stdin.buffer.read().split()
    if not rows:
        return
    n = int(rows[0])
    intervals = []
    index = 1
    for _ in range(n):
        start = int(rows[index])
        end = int(rows[index + 1])
        index += 2
        intervals.append((start, end))
    intervals.sort()
    best = [1] * n
    for i in range(n):
        for j in range(i):
            if intervals[j][1] <= intervals[i][0]:
                best[i] = max(best[i], best[j] + 1)
    print(max(best))


main()
'''),
    'CODE-P10': ('双重循环直接数逆序对', '''import sys


def main():
    data = list(map(int, sys.stdin.buffer.read().split()))
    if not data:
        return
    n = data[0]
    values = data[1:1 + n]
    pairs = 0
    for left in range(n):
        for right in range(left + 1, n):
            if values[left] > values[right]:
                pairs += 1
    print(pairs)


main()
'''),
    'CODE-P18': ('O(n^2) 动态规划求最长上升子序列', '''import sys


def main():
    data = list(map(int, sys.stdin.buffer.read().split()))
    if not data:
        return
    n = data[0]
    values = data[1:1 + n]
    best = [1] * n
    for i in range(1, n):
        for j in range(i):
            if values[j] < values[i]:
                best[i] = max(best[i], best[j] + 1)
    print(max(best))


main()
'''),
    'CODE-P63': ('排序后相邻比较找出只出现一次的数', '''import sys


def main():
    data = list(map(int, sys.stdin.buffer.read().split()))
    n = data[0]
    values = sorted(data[1:1 + n])
    answer = values[-1]
    index = 0
    while index + 1 < n:
        if values[index] != values[index + 1]:
            answer = values[index]
            break
        index += 2
    print(answer)


main()
'''),
    'CODE-P49': ('每次询问线性扫描', '''import sys


def main():
    data = list(map(int, sys.stdin.buffer.read().split()))
    n, q = data[0], data[1]
    values = data[2:2 + n]
    out = []
    pos = 2 + n
    for _ in range(q):
        target = data[pos]
        pos += 1
        found = -1
        for index in range(n):
            if values[index] == target:
                found = index + 1
                break
        out.append(str(found))
    sys.stdout.write('\\n'.join(out) + '\\n')


main()
'''),
}


# --------------------------------------------------------------------- helpers


def load_bank() -> dict[str, dict]:
    return {question['code']: question for question in
            json.loads(QUESTION_BANK.read_text(encoding='utf-8'))}


def reference_python(bank: dict[str, dict], code: str) -> str:
    for solution in bank[code]['reference_solutions']:
        if solution['language'] == 'Python':
            return solution['content']
    raise KeyError(f'{code} has no Python reference solution')


def token_stream(source: str, language: str = 'python3') -> list[tuple[str, str]]:
    return [(token.kind, token.text) for token in similarity.tokenize_source(source, language)]


def run_program(source: str, stdin_text: str, workdir: pathlib.Path,
                timeout: float = 20.0) -> tuple[int, str, str]:
    (workdir / 'main.py').write_text(source, encoding='utf-8')
    try:
        finished = subprocess.run([sys.executable, '-I', 'main.py'], cwd=workdir,
                                  input=stdin_text.encode('utf-8'), capture_output=True,
                                  timeout=timeout)
    except subprocess.TimeoutExpired:
        return 124, '', 'timeout'
    return finished.returncode, finished.stdout.decode('utf-8', 'replace'), \
        finished.stderr.decode('utf-8', 'replace')


def similarity_of(left: str, right: str) -> dict:
    """Similarity of two submissions of the same (hypothetical) item."""
    result = similarity.compare([
        {'answer_key': 'left', 'content': left, 'language': 'python3'},
        {'answer_key': 'right', 'content': right, 'language': 'python3'},
    ], threshold=0.0)
    if not result.pairs:
        return {'similarity': 0.0}
    return result.pairs[0]


def distribution(values: list[float]) -> dict:
    if not values:
        return {'count': 0, 'min': None, 'median': None, 'mean': None, 'max': None}
    ordered = sorted(values)
    return {
        'count': len(values),
        'min': round(ordered[0], 6),
        'median': round(statistics.median(ordered), 6),
        'mean': round(statistics.mean(ordered), 6),
        'max': round(ordered[-1], 6),
    }


# ----------------------------------------------------------- source rewriting


BUILTIN_NAMES = frozenset(dir(builtins))


def _imported_names(source: str) -> set[str]:
    """Names bound by ``import`` / ``from ... import`` statements.

    A rename must not touch a module name: ``import sys`` becoming
    ``import local_0`` is a different program, not a cosmetic edit.
    """
    names: set[str] = set()
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return names
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.asname or alias.name.split('.')[0])
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                names.add(alias.asname or alias.name)
            if node.module:
                names.add(node.module.split('.')[0])
    return names


def _source_offsets(source: str) -> list[int]:
    offsets = []
    offset = 0
    for line in source.splitlines(keepends=True):
        offsets.append(offset)
        offset += len(line)
    return offsets


def _apply_edits(source: str, edits: list[tuple[int, int, str]]) -> str:
    rewritten = source
    for start, end, replacement in sorted(edits, reverse=True):
        rewritten = rewritten[:start] + replacement + rewritten[end:]
    return rewritten


def _keyword_argument_names(source: str) -> set[str]:
    """Names used as keyword arguments anywhere in the file.

    ``sorted(x, key=...)`` binds the callee's parameter, not a local variable:
    renaming it would break the library call. Such a name is therefore never
    renamed anywhere in the file, which is conservative but stays correct.
    """
    names: set[str] = set()
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return names
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            for keyword_node in node.keywords:
                if keyword_node.arg:
                    names.add(keyword_node.arg)
    return names


def rename_identifiers(source: str) -> str:
    """Rename the program's own identifiers consistently.

    Attributes (the name after a dot), keyword arguments, keywords, builtins and
    imported module names keep their spelling, so the rewrite stays a renaming
    and not a semantic change.
    """
    tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    starts = _source_offsets(source)
    protected = (BUILTIN_NAMES | _imported_names(source) | _keyword_argument_names(source)
                 | {'self', 'cls'})
    mapping: dict[str, str] = {}
    edits: list[tuple[int, int, str]] = []
    previous = None
    for token in tokens:
        if token.type == tokenize.NAME and previous is not None \
                and previous.type == tokenize.OP and previous.string == '.':
            previous = token
            continue
        previous = token
        if token.type != tokenize.NAME:
            continue
        name = token.string
        if keyword.iskeyword(name) or name in protected:
            continue
        if name.startswith('__') and name.endswith('__'):
            continue
        replacement = mapping.setdefault(name, f'local_{len(mapping)}')
        (start_row, start_col), (end_row, end_col) = token.start, token.end
        edits.append((starts[start_row - 1] + start_col, starts[end_row - 1] + end_col, replacement))
    return _apply_edits(source, edits)


def _comment_edits(source: str, replacement: str) -> list[tuple[int, int, str]]:
    tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    starts = _source_offsets(source)
    edits = []
    for token in tokens:
        if token.type != tokenize.COMMENT:
            continue
        (start_row, start_col), (end_row, end_col) = token.start, token.end
        edits.append((starts[start_row - 1] + start_col, starts[end_row - 1] + end_col, replacement))
    return edits


def cosmetic_rewrite(source: str) -> str:
    """Rename identifiers, replace every comment and halve the indentation width.

    All three edits are exactly what a student does to disguise a copy, and none
    of them changes the token stream the winnowing sketch is computed from.
    """
    renamed = rename_identifiers(source)
    rewritten = _apply_edits(renamed, _comment_edits(renamed, '# 换过的注释'))
    lines = []
    for line in rewritten.splitlines():
        stripped = line.lstrip(' ')
        indent = len(line) - len(stripped)
        if indent and indent % 4 == 0:
            indent = indent // 4 * 2
        lines.append(' ' * indent + stripped)
    return '\n'.join(lines) + '\n\n# 文件末尾附注，用于验证注释不影响相似度\n'


class _LightRewrite(ast.NodeTransformer):
    """Rewrite without inserting statements.

    Two mechanical edits that keep the token count close to the original:
    ``x += y`` becomes ``x = x + y`` and a safe comparison is flipped. Both are
    exactly the kind of edit a student makes when told to "change the code a
    little".
    """

    def visit_AugAssign(self, node):
        self.generic_visit(node)
        target = ast.parse(ast.unparse(node.target), mode='eval').body
        return ast.Assign(targets=[node.target],
                          value=ast.BinOp(left=target, op=node.op, right=node.value))

    def visit_Compare(self, node):
        self.generic_visit(node)
        if len(node.ops) == 1 and type(node.ops[0]) in (ast.Lt, ast.Gt, ast.LtE, ast.GtE):
            flipped = {ast.Lt: ast.Gt, ast.Gt: ast.Lt,
                       ast.LtE: ast.GtE, ast.GtE: ast.LtE}[type(node.ops[0])]()
            if _pure(node.left) and _pure(node.comparators[0]):
                return ast.Compare(left=node.comparators[0], ops=[flipped],
                                   comparators=[node.left])
        return node


class _HeavyRewrite(ast.NodeTransformer):
    """Rewrite that also inserts statements.

    On top of the light edits, a nested call argument such as ``int(data[0])``
    is materialised into a temporary first, and every loop body starts with one
    redundant assignment. This is what a student does when deliberately
    restructuring a copied program, and it changes the *number* of tokens.
    """

    def __init__(self) -> None:
        self.counter = 0

    def _temporary(self) -> str:
        self.counter += 1
        return f'_rewritten_{self.counter}'

    def visit_Assign(self, node):
        self.generic_visit(node)
        value = node.value
        if isinstance(value, ast.Call) and len(value.args) == 1 and not value.keywords:
            argument = value.args[0]
            if isinstance(argument, (ast.Call, ast.Subscript)):
                temporary = self._temporary()
                return [
                    ast.Assign(targets=[ast.Name(id=temporary, ctx=ast.Store())], value=argument),
                    ast.Assign(targets=node.targets,
                               value=ast.Call(func=value.func, args=[ast.Name(id=temporary, ctx=ast.Load())],
                                              keywords=[])),
                ]
        return node

    def visit_AugAssign(self, node):
        self.generic_visit(node)
        target = ast.parse(ast.unparse(node.target), mode='eval').body
        return ast.Assign(targets=[node.target],
                          value=ast.BinOp(left=target, op=node.op, right=node.value))

    def visit_Compare(self, node):
        self.generic_visit(node)
        if len(node.ops) == 1 and type(node.ops[0]) in (ast.Lt, ast.Gt, ast.LtE, ast.GtE):
            flipped = {ast.Lt: ast.Gt, ast.Gt: ast.Lt,
                       ast.LtE: ast.GtE, ast.GtE: ast.LtE}[type(node.ops[0])]()
            if _pure(node.left) and _pure(node.comparators[0]):
                return ast.Compare(left=node.comparators[0], ops=[flipped],
                                   comparators=[node.left])
        return node

    def _pad(self, node):
        node.body = [ast.Assign(targets=[ast.Name(id='_rewritten_pad', ctx=ast.Store())],
                                value=ast.Constant(value=0))] + node.body
        return node

    def visit_For(self, node):
        self.generic_visit(node)
        return self._pad(node)

    def visit_While(self, node):
        self.generic_visit(node)
        return self._pad(node)


def _pure(node: ast.AST) -> bool:
    """True when evaluating ``node`` twice is free of side effects."""
    for child in ast.walk(node):
        if isinstance(child, (ast.Call, ast.Await, ast.NamedExpr, ast.Subscript, ast.Yield)):
            return False
    return True


def light_structural_rewrite(source: str) -> str:
    tree = _LightRewrite().visit(ast.parse(source))
    ast.fix_missing_locations(tree)
    return ast.unparse(tree) + '\n'


def heavy_structural_rewrite(source: str) -> str:
    tree = _HeavyRewrite().visit(ast.parse(source))
    ast.fix_missing_locations(tree)
    return ast.unparse(tree) + '\n'


def verify_equivalent(bank: dict[str, dict], code: str, original: str, rewritten: str,
                      workdir: pathlib.Path, limit: int = 3) -> dict:
    """Run both programs on the problem's own test cases and compare stdout."""
    tests = bank[code].get('tests') or []
    checked = 0
    for case in tests[:limit]:
        expected = case.get('output', '')
        original_code, original_out, original_err = run_program(original, case['input'], workdir)
        new_code, new_out, new_err = run_program(rewritten, case['input'], workdir)
        checked += 1
        if original_code != 0 or new_code != 0:
            return {'ok': False, 'cases': checked, 'reason': 'RUNTIME_ERROR',
                    'detail': (original_err or new_err).strip()[:160]}
        if original_out.strip() != new_out.strip():
            return {'ok': False, 'cases': checked, 'reason': 'OUTPUT_DIFFERS'}
        if original_out.strip() != expected.strip():
            return {'ok': False, 'cases': checked, 'reason': 'REFERENCE_OUTPUT_DIFFERS'}
    return {'ok': True, 'cases': checked}


# ------------------------------------------------------- similarity experiments


def experiment_transform(bank: dict[str, dict], rewrite, workdir: pathlib.Path,
                         *, name: str, purpose: str) -> dict:
    """Compare every reference solution against its rewrite."""
    rows: list[dict] = []
    verified_programs = 0
    verified_cases = 0
    rewrite_failures: list[dict] = []
    for code in sorted(bank):
        original = reference_python(bank, code)
        try:
            rewritten = rewrite(original)
        except (SyntaxError, ValueError) as error:
            rewrite_failures.append({'code': code, 'reason': f'{type(error).__name__}: {error}'[:120]})
            continue
        try:
            compile(rewritten, '<rewritten>', 'exec')
        except SyntaxError as error:
            rewrite_failures.append({'code': code, 'reason': f'NOT_COMPILABLE: {error}'[:120]})
            continue
        verification = verify_equivalent(bank, code, original, rewritten, workdir)
        if verification['ok']:
            verified_programs += 1
            verified_cases += verification['cases']
        pair = similarity_of(original, rewritten)
        rows.append({
            'code': code,
            'tokens_before': len(token_stream(original)),
            'tokens_after': len(token_stream(rewritten)),
            'fingerprints_before': len(similarity.sketch(code, original, 'python3').positions),
            'similarity': float(pair.get('similarity', 0.0)),
            'shared_fingerprints': pair.get('shared_fingerprints'),
            'semantics_verified': verification['ok'],
            'cases_checked': verification['cases'],
            'verification_reason': verification.get('reason'),
        })
    similarities = [row['similarity'] for row in rows]
    rows.sort(key=lambda row: row['similarity'])
    below = [row for row in rows if row['similarity'] < THRESHOLD]
    return {
        'name': name,
        'purpose': purpose,
        'programs': len(rows),
        'parameters': {'k': similarity.KGRAM, 'window': similarity.WINDOW,
                       'minimum_tokens': similarity.DEFAULT_MINIMUM_TOKENS,
                       'threshold': THRESHOLD},
        'semantics_verified_programs': verified_programs,
        'semantics_verified_cases': verified_cases,
        'rewrite_failures': rewrite_failures,
        'distribution': distribution(similarities),
        'at_or_above_threshold': len(rows) - len(below),
        'below_threshold': len(below),
        'below_threshold_codes': [row['code'] for row in below],
        'rows': rows,
    }


def experiment_cosmetic(bank: dict[str, dict], workdir: pathlib.Path) -> dict:
    block = experiment_transform(
        bank, cosmetic_rewrite, workdir,
        name='改名 + 改注释 + 改缩进',
        purpose='验证词法规格化后，纯表面改写不应改变指纹，相似度应为 1.0')
    identical = 0
    for row in block['rows']:
        original = reference_python(bank, row['code'])
        if token_stream(original) == token_stream(cosmetic_rewrite(original)):
            identical += 1
    block['identical_token_stream_count'] = identical
    return block


def experiment_structural_light(bank: dict[str, dict], workdir: pathlib.Path) -> dict:
    return experiment_transform(
        bank, light_structural_rewrite, workdir,
        name='结构改写（等价写法，不增删语句）',
        purpose='把 += 改成 = 与 +、调换比较顺序；语法树等价、记号数接近，'
                '用于验证结构改写后相似度仍高于 0.5')


def experiment_structural_heavy(bank: dict[str, dict], workdir: pathlib.Path) -> dict:
    return experiment_transform(
        bank, heavy_structural_rewrite, workdir,
        name='结构改写（语句拆分 + 插入冗余语句）',
        purpose='在上面的改写之外，把嵌套调用拆成临时变量、在每个循环体开头插入一条冗余赋值；'
                '验证插入语句对 12 记号 k-gram 的破坏程度')


def experiment_unrelated_same_problem(bank: dict[str, dict],
                                      workdir: pathlib.Path) -> dict:
    rows = []
    for code in sorted(ALTERNATIVE_IMPLEMENTATIONS):
        label, implementation = ALTERNATIVE_IMPLEMENTATIONS[code]
        original = reference_python(bank, code)
        verification = verify_equivalent(bank, code, original, implementation, workdir,
                                         limit=len(bank[code].get('tests') or []))
        pair = similarity_of(original, implementation)
        rows.append({
            'code': code,
            'title': bank[code]['title'],
            'alternative': label,
            'tokens_reference': len(token_stream(original)),
            'tokens_alternative': len(token_stream(implementation)),
            'correct': verification['ok'],
            'cases_checked': verification['cases'],
            'similarity': float(pair.get('similarity', 0.0)),
            'shared_fingerprints': pair.get('shared_fingerprints'),
        })
    values = [row['similarity'] for row in rows]
    return {
        'name': '无关实现：同一道题的不同算法',
        'purpose': '判据要求无关实现落在 0 对或低于阈值；这里用同一道题的两套正确算法检验误报',
        'programs': len(rows),
        'distribution': distribution(values),
        'at_or_above_threshold': sum(1 for value in values if value >= THRESHOLD),
        'rows': rows,
    }


# Three genuinely independent implementations of one standard algorithm (activity
# selection). No copying: the problem dictates the whole script, so the only
# freedom is naming and statement order. Written in two idiom regimes because the
# classroom idiom is what a course actually standardises.
HONEST_SHORT_VARIED_IDIOM = (
    """import sys

def main():
    data = sys.stdin.read().split()
    n = int(data[0])
    acts = []
    idx = 1
    for _ in range(n):
        s, t = int(data[idx]), int(data[idx+1])
        idx += 2
        acts.append((s, t))
    acts.sort(key=lambda x: x[1])
    count = 0
    last = -10**18
    for s, t in acts:
        if s >= last:
            count += 1
            last = t
    print(count)

main()
""",
    """n = int(input())
intervals = []
for _ in range(n):
    start, end = map(int, input().split())
    intervals.append((end, start))
intervals.sort()
chosen = 0
free_at = float('-inf')
for end, start in intervals:
    if start >= free_at:
        chosen += 1
        free_at = end
print(chosen)
""",
    """import sys
input = sys.stdin.readline

n = int(input())
A = []
for i in range(n):
    l, r = map(int, input().split())
    A.append([r, l])
A.sort()
ans = 0
cur = -1
for r, l in A:
    if l > cur or l == cur:
        ans += 1
        cur = r
print(ans)
""",
)

HONEST_SHORT_SHARED_IDIOM = (
    """import sys
data = sys.stdin.read().split()
n = int(data[0])
acts = []
idx = 1
for _ in range(n):
    acts.append((int(data[idx]), int(data[idx+1])))
    idx += 2
acts.sort(key=lambda x: x[1])
count = 0
last = -1
for s, t in acts:
    if s >= last:
        count += 1
        last = t
print(count)
""",
    """import sys
data = sys.stdin.read().split()
n = int(data[0])
intervals = []
for i in range(n):
    intervals.append((int(data[2*i+1]), int(data[2*i+2])))
intervals.sort(key=lambda pair: pair[1])
chosen = 0
free_at = -1
for begin, end in intervals:
    if begin >= free_at:
        chosen += 1
        free_at = end
print(chosen)
""",
    """import sys
tokens = sys.stdin.read().split()
n = int(tokens[0])
pairs = []
pos = 1
for _ in range(n):
    pairs.append((int(tokens[pos]), int(tokens[pos + 1])))
    pos += 2
pairs.sort(key=lambda item: item[1])
answer = 0
finish = -1
for left, right in pairs:
    if left >= finish:
        answer += 1
        finish = right
print(answer)
""",
)

HONEST_LONG_INDEPENDENT = (
    """import sys
def main():
    data = sys.stdin.buffer.read().split()
    n = int(data[0])
    stones = [int(x) for x in data[1:1+n]]
    prefix = [0] * (n + 1)
    for i in range(n):
        prefix[i+1] = prefix[i] + stones[i]
    INF = float('inf')
    dp = [[0] * n for _ in range(n)]
    for length in range(2, n + 1):
        for i in range(0, n - length + 1):
            j = i + length - 1
            best = INF
            total = prefix[j+1] - prefix[i]
            for k in range(i, j):
                cost = dp[i][k] + dp[k+1][j] + total
                if cost < best:
                    best = cost
            dp[i][j] = best
    print(dp[0][n-1])
main()
""",
    """import sys

def solve():
    tokens = sys.stdin.buffer.read().split()
    n = int(tokens[0])
    w = list(map(int, tokens[1:n+1]))
    pre = [0]*(n+1)
    for idx in range(1, n+1):
        pre[idx] = pre[idx-1] + w[idx-1]
    f = [[0]*n for _ in range(n)]
    for span in range(2, n+1):
        left = 0
        while left + span <= n:
            right = left + span - 1
            f[left][right] = min(
                f[left][m] + f[m+1][right] + pre[right+1] - pre[left]
                for m in range(left, right)
            )
            left += 1
    print(f[0][n-1])

solve()
""",
)


def _pairwise(group: tuple[str, ...], *, label: str) -> dict:
    items = [dict(answer_key=f"honest-{index}", content=content, language='python3')
             for index, content in enumerate(group)]
    result = similarity.compare(items, threshold=0.0)
    rows = [{'left': row['left_key'], 'right': row['right_key'],
             'similarity': float(row['similarity']),
             'longest_run_tokens': row['longest_run_tokens'],
             'left_tokens': row['left_tokens'], 'right_tokens': row['right_tokens']}
            for row in result.pairs]
    return {'label': label, 'pairs': rows,
            'max_similarity': max((row['similarity'] for row in rows), default=0.0),
            'at_or_above_threshold': sum(1 for row in rows if row['similarity'] >= THRESHOLD),
            'pair_count': len(rows)}


def experiment_honest_baseline() -> dict:
    """How similar are two students who did the work independently?

    Every other similarity experiment compares a reference solution with a
    deliberately rewritten copy or with a different algorithm. None of them
    answered the question a teacher actually faces: on a short formulaic problem,
    where the statement dictates almost the whole script, what does honest
    independent work score? That baseline decides whether a threshold has any
    calibration meaning.
    """
    varied = _pairwise(HONEST_SHORT_VARIED_IDIOM, label='短题目 · 独立完成 · I/O 习惯各异')
    shared = _pairwise(HONEST_SHORT_SHARED_IDIOM, label='短题目 · 独立完成 · 统一 I/O 惯用法')
    long_pair = _pairwise(HONEST_LONG_INDEPENDENT, label='长题目 · 独立完成 · 同一算法')
    return {
        'name': '独立完成基线：同一算法由不同人独立实现时的相似度',
        'purpose': ('给出阈值的校准基线。若独立完成也常常超过阈值，则"超过阈值"本身不能作为抄袭证据，'
                    '证据强度必须与程序长度一起呈现。'),
        'parameters': {'k': similarity.KGRAM, 'window': similarity.WINDOW,
                       'threshold': THRESHOLD, 'max_pairs': similarity.MAX_PAIRS},
        'groups': {'varied_idiom_short': varied, 'shared_idiom_short': shared,
                   'independent_long': long_pair},
        'summary': {
            'short_independent_max': max(varied['max_similarity'], shared['max_similarity']),
            'short_independent_at_or_above': shared['at_or_above_threshold'],
            'long_independent_max': long_pair['max_similarity'],
        },
        'notes': [
            '三份短程序都实现活动安排贪心，彼此独立写作，没有复制关系',
            '统一 I/O 惯用法模拟被同一门课教出来的班级',
            '长程序是石子合并区间 DP 的两份独立实现',
        ],
    }


def experiment_unrelated_cross_problem(bank: dict[str, dict]) -> dict:
    codes = sorted(bank)
    sketches = {code: similarity.sketch(code, reference_python(bank, code), 'python3')
                for code in codes}
    values: list[float] = []
    rows = []
    for index, left in enumerate(codes):
        for right in codes[index + 1:]:
            left_sketch, right_sketch = sketches[left], sketches[right]
            left_size = len(left_sketch.positions)
            right_size = len(right_sketch.positions)
            if not left_size or not right_size:
                value = 0.0
                shared = 0
            else:
                shared = len(set(left_sketch.positions) & set(right_sketch.positions))
                value = max(shared / left_size, shared / right_size)
            values.append(value)
            if value >= THRESHOLD:
                rows.append({'left': left, 'right': right, 'similarity': round(value, 6),
                             'shared_fingerprints': shared})
    rows.sort(key=lambda row: -row['similarity'])
    item = [{'answer_key': code, 'content': reference_python(bank, code), 'language': 'python3'}
            for code in codes]
    batch = similarity.compare(item, threshold=THRESHOLD)
    ordered = sorted(values)
    return {
        'name': '无关实现：70 道不同题目的参考解两两比较',
        'purpose': '考察完全没有抄袭关系的代码之间是否会被阈值判成相似（误报率）',
        'submissions': len(codes),
        'pairs_scanned': len(values),
        'pairs_at_or_above_threshold': len(rows),
        'false_positive_rate': round(len(rows) / len(values), 6) if values else 0.0,
        'distribution': distribution(values),
        'percentiles': {'p50': round(ordered[len(ordered) // 2], 6),
                        'p90': round(ordered[int(len(ordered) * 0.9)], 6),
                        'p99': round(ordered[int(len(ordered) * 0.99)], 6)},
        'compare_pair_count': len(batch.pairs),
        'compare_cluster_count': len(batch.clusters),
        'top_rows': rows[:10],
    }


def experiment_insertion_sensitivity(bank: dict[str, dict]) -> dict:
    """How much does one inserted statement cost?

    The heavy rewrite showed that inserting statements is what breaks the
    similarity. This isolates the cause: the same program with 1, 2, 3, 4 and 8
    redundant assignments inserted at spread-out positions. Each insertion
    breaks the k-grams that straddle it, so the loss should grow with the number
    of insertions rather than with the size of the program.
    """
    code = 'CODE-P26'
    source = reference_python(bank, code)
    base_sketch = similarity.sketch('base', source, 'python3')
    body = source.splitlines()

    def indent_of(line: str) -> int:
        return len(line) - len(line.lstrip(' '))

    # Only insert directly after a statement whose following line is at the same
    # or a lower indentation, so the inserted line never lands inside a block it
    # would break, and never right after a line ending with ':'.
    safe_indices = []
    for index, line in enumerate(body[:-1]):
        stripped = line.strip()
        if not stripped or stripped.startswith('#'):
            continue
        if stripped.endswith(':'):
            continue
        if indent_of(body[index + 1]) <= indent_of(line):
            safe_indices.append(index)

    rows = []
    for count in (1, 2, 3, 4, 8):
        step = max(1, len(safe_indices) // count)
        chosen = safe_indices[::step][:count]
        rewritten_lines = list(body)
        for offset, line_index in enumerate(sorted(chosen, reverse=True)):
            indent = ' ' * indent_of(rewritten_lines[line_index])
            rewritten_lines.insert(line_index + 1, f'{indent}inserted_{offset} = {offset}')
        rewritten = '\n'.join(rewritten_lines) + '\n'
        try:
            compile(rewritten, '<insertion>', 'exec')
        except SyntaxError as error:
            rows.append({'insertions': count, 'similarity': None,
                         'error': f'NOT_COMPILABLE: {error}'[:120]})
            continue
        sketch = similarity.sketch('rewritten', rewritten, 'python3')
        shared = len(set(base_sketch.positions) & set(sketch.positions))
        pair = similarity_of(source, rewritten)
        rows.append({
            'insertions': count,
            'tokens_before': base_sketch.token_count,
            'tokens_after': sketch.token_count,
            'unique_fingerprints_before': len(base_sketch.positions),
            'unique_fingerprints_after': len(sketch.positions),
            'shared_fingerprints': shared,
            'similarity': float(pair.get('similarity', 0.0)),
            'longest_run_tokens': pair.get('longest_run_tokens'),
        })
    return {
        'name': '插入敏感性：同一份代码插入 1/2/3/4/8 条冗余赋值',
        'purpose': '定量说明结构改写里的“插入语句”为什么会让相似度掉得这么多',
        'source': code,
        'parameters': {'k': similarity.KGRAM, 'window': similarity.WINDOW,
                       'threshold': THRESHOLD},
        'rows': rows,
    }


def build_report(*, similarity_blocks: dict, wall_seconds: float) -> dict:
    return {
        'meta': {
            'seed': SEED,
            'python': sys.version.split()[0],
            'platform': platform.platform(),
            'generated_at': time.strftime('%Y-%m-%dT%H:%M:%S'),
            'wall_seconds': round(wall_seconds, 1),
            'question_bank': str(QUESTION_BANK.relative_to(REPO_ROOT)),
            'similarity_parameters': {
                'k': similarity.KGRAM, 'window': similarity.WINDOW,
                'minimum_tokens': similarity.DEFAULT_MINIMUM_TOKENS,
                'threshold': THRESHOLD, 'max_pairs': similarity.MAX_PAIRS,
            },
            'notes': [
                '全部相似度来自 similarity.compare，与教师页面走同一条路径',
                '耗时是对真实进程的墙钟测量，每次运行会有波动；结构、类别和指纹数与运行无关',
                '脚本不连接数据库、不读名册、不联网',
                '复杂度实验已迁移到 scripts/experiment_complexity_trace.py（执行轨迹计数路线）',
            ],
        },
        'similarity': similarity_blocks,
    }


def summary_line(report: dict) -> str:
    blocks = report['similarity']
    cosmetic = blocks['cosmetic']
    light = blocks['structural_light']
    heavy = blocks['structural_heavy']
    same_problem = blocks['unrelated_same_problem']
    cross = blocks['unrelated_cross_problem']
    scale = blocks['scale']
    scale_text = '/'.join(f"{row['seconds_median']:.2f}" for row in scale['rows'])
    return (
        'SUMMARY '
        f"similarity: cosmetic median={cosmetic['distribution']['median']:.6f} "
        f"({cosmetic['below_threshold']}/{cosmetic['programs']} below), "
        f"structural_light median={light['distribution']['median']:.6f} "
        f"({light['below_threshold']}/{light['programs']} below), "
        f"structural_heavy median={heavy['distribution']['median']:.6f} "
        f"({heavy['below_threshold']}/{heavy['programs']} below), "
        f"same_problem_alts>={THRESHOLD}: {same_problem['at_or_above_threshold']}/{same_problem['programs']}, "
        f"cross_problem>={THRESHOLD}: {cross['pairs_at_or_above_threshold']}/{cross['pairs_scanned']}, "
        f"scale(20/50/100/200)s={scale_text} exponent={scale['loglog_exponent']:.2f}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=pathlib.Path,
                        help='把完整 JSON 报告写到这个路径（stdout 只保留汇总行）')
    arguments = parser.parse_args(argv)

    started = time.perf_counter()
    bank = load_bank()
    workdir = pathlib.Path(tempfile.mkdtemp(prefix='similarity-experiment-'))

    similarity_blocks = {}
    similarity_blocks['cosmetic'] = experiment_cosmetic(bank, workdir)
    similarity_blocks['structural_light'] = experiment_structural_light(bank, workdir)
    similarity_blocks['structural_heavy'] = experiment_structural_heavy(bank, workdir)
    similarity_blocks['insertion_sensitivity'] = experiment_insertion_sensitivity(bank)
    similarity_blocks['unrelated_same_problem'] = experiment_unrelated_same_problem(bank, workdir)
    similarity_blocks['unrelated_cross_problem'] = experiment_unrelated_cross_problem(bank)
    similarity_blocks['scale'] = experiment_scale(bank)
    similarity_blocks['honest_baseline'] = experiment_honest_baseline()

    report = build_report(similarity_blocks=similarity_blocks,
                          wall_seconds=time.perf_counter() - started)
    if arguments.output is not None:
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n',
                                    encoding='utf-8')
    else:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    print(summary_line(report), flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
