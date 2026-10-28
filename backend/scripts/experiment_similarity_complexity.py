#!/usr/bin/env python3
"""Reproducible experiments for the similarity detector and the complexity estimator.

The module drives the real algorithm code, not a re-implementation:

* ``app.analysis.algorithms.similarity`` is used through its public functions
  ``sketch`` / ``compare``, so the numbers below are exactly what the teacher
  page would show for the same inputs.
* ``app.analysis.probe`` generates each size ladder and spawns real child
  processes; ``app.analysis.algorithms.complexity`` classifies the measured
  ladder and merges it with the static analysis, exactly as the worker does.

Nothing here opens a database connection, reads a roster or touches the
network. The only inputs are the reference solutions in
``data/formatted/questions.programming.json`` and the per-problem ladder
definitions in ``app.analysis.profiles.PROFILES``.

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

from app.analysis import probe
from app.analysis import profiles
from app.analysis.algorithms import complexity
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


def experiment_fit_calibration(bank: dict[str, dict]) -> dict:
    """Feed noise-free ladders to the real fitter and record what it reports.

    For each complexity class this builds ``t = 12 ms + c * f(n)`` from the
    module's own growth functions, choosing ``c`` so the first rung sits 24 ms
    above the floor. There is no measurement noise at all, so any wrong answer
    below is a property of the fitting rule rather than of the machine.
    """
    classes = ('O(1)', 'O(log n)', 'O(n)', 'O(n log n)', 'O(n^2)', 'O(n^3)')
    spans = (4, 8, 16, 64, 256)
    rows = []
    for span in spans:
        sizes = sorted({int(round(256 * span ** (step / 6))) for step in range(7)})
        for name in classes:
            function = complexity.GROWTH_FUNCTIONS[name]
            first = function(sizes[0])
            coefficient = 24.0 / first if first else 0.0
            points = [complexity.Measurement(n=size, wall_ms=12.0 + coefficient * function(size),
                                            adjusted_ms=coefficient * function(size),
                                            peak_rss_kib=None, verdict='OK')
                      for size in sizes]
            fit = complexity.fit_growth(points)
            times = [point.wall_ms for point in points]
            mean_time = sum(times) / len(times)
            total = sum((value - mean_time) ** 2 for value in times)
            candidates = {}
            for candidate in complexity.TIME_CLASSES:
                basis = [complexity.GROWTH_FUNCTIONS[candidate](size) for size in sizes]
                coefficients = complexity._fit_with_offset(basis, times)  # noqa: SLF001
                if coefficients is None:
                    continue
                a, b = coefficients
                residuals = [value - (a * item + b) for value, item in zip(times, basis)]
                r2 = 1.0 if total <= 1e-12 else 1 - sum(residual * residual
                                                        for residual in residuals) / total
                candidates[candidate] = round(max(0.0, min(1.0, r2)), 6)
            ranked = sorted(candidates.items(), key=lambda item: -item[1])
            rows.append({
                'ideal_class': name,
                'ladder_span': span,
                'rungs': len(sizes),
                'sizes': list(sizes),
                'reported_class': fit.fitted_class,
                'reported_r2': round(fit.r2, 6),
                'confidence': fit.confidence,
                'correct': fit.fitted_class == name,
                'r2_by_class': dict(ranked),
                'top_two_gap': (round(ranked[0][1] - ranked[1][1], 6)
                                if len(ranked) >= 2 else None),
            })
    wrong = [row for row in rows if not row['correct']]
    return {
        'name': '拟合器标定：把无噪声的理想增长曲线喂给同一个 fit_growth',
        'purpose': '分离“测量噪声”与“拟合规则”两类误差：这里没有任何噪声，'
                   '报错的部分只能来自规则本身（R² 只差 0.005 以内就取更低阶，'
                   '而 O(n log n) 相对 O(n) 的 R² 优势始终小于这个门槛）',
        'parameters': {'floor_ms': 12.0, 'amplitude_at_first_rung_ms': 24.0,
                       'rungs': 7, 'tie_margin': 0.005},
        'rows': rows,
        'misclassified': len(wrong),
        'misclassified_detail': [{'ideal': row['ideal_class'], 'reported': row['reported_class'],
                                  'span': row['ladder_span'], 'confidence': row['confidence'],
                                  'top_two_gap': row['top_two_gap']} for row in wrong],
    }


def mutate_once(source: str, rng: random.Random, salt: int) -> str:
    """One tiny edit: rename one *own* identifier and append a comment line.

    Keywords must never be picked, and the choice is restricted to names that
    the file binds itself (assignments, function parameters, function names).
    Otherwise the mutation can hit ``if`` or a module name and change the token
    stream far more than "one rename" implies.
    """
    own_names = _locally_bound_names(source)
    tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    starts = _source_offsets(source)
    candidates = [token for token in tokens
                  if token.type == tokenize.NAME and token.string in own_names
                  and not keyword.iskeyword(token.string)]
    if not candidates:
        return source + f'\n# variant {salt}\n'
    victim = rng.choice(candidates).string
    edits = []
    previous = None
    for token in tokens:
        if token.type == tokenize.NAME and previous is not None and previous.type == tokenize.OP \
                and previous.string == '.':
            previous = token
            continue
        previous = token
        if token.type == tokenize.NAME and token.string == victim:
            (start_row, start_col), (end_row, end_col) = token.start, token.end
            edits.append((starts[start_row - 1] + start_col,
                          starts[end_row - 1] + end_col, f'{victim}_v{salt}'))
    return _apply_edits(source, edits) + f'\n# variant {salt}\n'


def _locally_bound_names(source: str) -> set[str]:
    """Names the source itself binds: assignments, parameters, function names."""
    names: set[str] = set()
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return names
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            names.add(node.name)
            for argument in node.args.args:
                names.add(argument.arg)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                for child in ast.walk(target):
                    if isinstance(child, ast.Name):
                        names.add(child.id)
        elif isinstance(node, (ast.AugAssign, ast.AnnAssign)):
            for child in ast.walk(node.target):
                if isinstance(child, ast.Name):
                    names.add(child.id)
        elif isinstance(node, ast.For):
            for child in ast.walk(node.target):
                if isinstance(child, ast.Name):
                    names.add(child.id)
    return names


def experiment_scale(bank: dict[str, dict]) -> dict:
    """Batch cost as the number of submissions grows."""
    base = reference_python(bank, SCALE_SOURCE)
    rng = random.Random(SEED)
    rows = []
    durations: list[tuple[int, float]] = []
    for size in SCALE_SIZES:
        item = [{'answer_key': f'submission-{index}',
                 'content': mutate_once(base, rng, index),
                 'language': 'python3'} for index in range(size)]
        sketches = [similarity.sketch(entry['answer_key'], entry['content'], 'python3')
                    for entry in item]
        unique_fingerprints = sum(len(sketch.positions) for sketch in sketches)
        selected_fingerprints = sum(len(sketch.fingerprints) for sketch in sketches)
        timings = []
        result = None
        for _ in range(SCALE_REPEATS):
            started = time.perf_counter()
            result = similarity.compare(item, threshold=THRESHOLD)
            timings.append(time.perf_counter() - started)
        median_seconds = statistics.median(timings)
        durations.append((size, median_seconds))
        pair_values = [float(pair['similarity']) for pair in result.pairs]
        rows.append({
            'submissions': size,
            'seconds_median': round(median_seconds, 4),
            'seconds_min': round(min(timings), 4),
            'seconds_max': round(max(timings), 4),
            'repeats': SCALE_REPEATS,
            'tokens_per_submission': len(token_stream(base)),
            'unique_fingerprints_per_submission': len(sketches[0].positions),
            'selected_fingerprints_per_submission': len(sketches[0].fingerprints),
            'unique_fingerprints_total': unique_fingerprints,
            'selected_fingerprints_total': selected_fingerprints,
            'candidate_pairs': size * (size - 1) // 2,
            'reported_pairs': len(result.pairs),
            'pairs_truncated': len(result.pairs) == similarity.MAX_PAIRS,
            'clusters': len(result.clusters),
            'cluster_sizes': sorted((cluster['size'] for cluster in result.clusters), reverse=True),
            'similarity_min': min(pair_values) if pair_values else None,
            'similarity_median': round(statistics.median(pair_values), 6) if pair_values else None,
        })
    # Empirical growth: fit log(seconds) = exponent * log(K) + c over the four
    # measurements, which is what the same fitting code does for a size ladder.
    xs = [math.log(size) for size, _ in durations]
    ys = [math.log(seconds) for _, seconds in durations]
    mean_x = sum(xs) / len(xs)
    mean_y = sum(ys) / len(ys)
    denominator = sum((value - mean_x) ** 2 for value in xs)
    exponent = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys)) / denominator
    resized = [rows[index]['seconds_median'] / rows[index - 1]['seconds_median']
               if rows[index - 1]['seconds_median'] else None
               for index in range(1, len(rows))]
    return {
        'name': f'规模实验：K 份 {SCALE_SOURCE} 的副本（各加一处改名与一行注释）',
        'purpose': '测 compare() 随提交数量增长的实际耗时与指纹规模，检验倒排索引实现的增长趋势',
        'source': SCALE_SOURCE,
        'tokens_per_submission': len(token_stream(base)),
        'parameters': {'k': similarity.KGRAM, 'window': similarity.WINDOW,
                       'threshold': THRESHOLD, 'max_pairs': similarity.MAX_PAIRS},
        'rows': rows,
        'doubling_ratios': [round(value, 3) for value in resized if value is not None],
        'loglog_exponent': round(exponent, 4),
    }


# ------------------------------------------------------- complexity experiments


CONSTANT_PROGRAM = '''import sys


def main():
    n = int(sys.stdin.buffer.read().split()[0])
    value = (n * 2654435761 + 12345) % 1000000007
    print(value % 7)


main()
'''

LOGARITHM_PROGRAM = '''import sys


def main():
    n = int(sys.stdin.buffer.read().split()[0])
    total = 0
    # 循环次数是常数，循环体里的二分步数随 log n 增长，因此总时间与 log n 成正比
    for _ in range(60000):
        low, high = 0, n
        while low < high:
            middle = (low + high) // 2
            if middle * middle < n:
                low = middle + 1
            else:
                high = middle
        total += low
    print(total % 7)


main()
'''

MERGE_SORT_PROGRAM = '''import sys


def merge_sort(values):
    if len(values) <= 1:
        return values
    middle = len(values) // 2
    left = merge_sort(values[:middle])
    right = merge_sort(values[middle:])
    merged = []
    i = j = 0
    while i < len(left) and j < len(right):
        if left[i] <= right[j]:
            merged.append(left[i])
            i += 1
        else:
            merged.append(right[j])
            j += 1
    merged.extend(left[i:])
    merged.extend(right[j:])
    return merged


def main():
    data = list(map(int, sys.stdin.buffer.read().split()))
    n = data[0]
    ordered = merge_sort(data[1:1 + n])
    print(sum(ordered[::max(1, n // 4)]) % 7)


main()
'''


def build_complexity_groups(bank: dict[str, dict]) -> list[dict]:
    """Six groups covering O(1) .. O(n^3).

    Five are the required O(1)/O(log n)/O(n)/O(n log n)/O(n^2) ladder; the sixth
    adds O(n^3) because the interval-DP reference solution is the only one that
    reaches the wall-clock guard, which is itself worth reporting.

    ``sizes``/``spec`` notes:
    * The hand-written groups declare the ladder through ``sizes`` because
      ``escalating_measure`` takes its sizes from ``probe.MAX_SIZES`` and only
      the input generator reads ``spec['max_n']``.
    * For CODE-P17 the profile cap is ``max_n=2000``, but the generator has no
      hard limit and the run is bounded only by the wall clock. The measurement
      below therefore passes an explicit ladder that stops at n = 4096.
    """
    groups = [
        {'key': 'O1', 'expected': 'O(1)', 'source': 'hand-written',
         'title': '常数时间：读入 n 后只做固定几步算术', 'program': CONSTANT_PROGRAM,
         'family': 'SINGLE_INT', 'spec': {'max_n': 10 ** 7, 'max': 10 ** 7}},
        {'key': 'Olog', 'expected': 'O(log n)', 'source': 'hand-written',
         'title': '对数时间：循环 6 万次、每次在 [0, n] 上二分', 'program': LOGARITHM_PROGRAM,
         'family': 'SINGLE_INT', 'spec': {'max_n': 10 ** 7, 'max': 10 ** 7}},
        {'key': 'On', 'expected': 'O(n)', 'source': 'reference:CODE-P63',
         'title': '线性：异或求只出现一次的数（参考解）', 'code': 'CODE-P63'},
        {'key': 'Onlog', 'expected': 'O(n log n)', 'source': 'hand-written',
         'title': '线性对数：自写归并排序后再取和', 'program': MERGE_SORT_PROGRAM,
         'family': 'INT_ARRAY', 'spec': {'max_n': 2 * 10 ** 6}},
        {'key': 'On2', 'expected': 'O(n^2)', 'source': 'reference:CODE-P17',
         'title': '平方：最长公共子序列滚动数组（参考解）', 'code': 'CODE-P17',
         'max_n_override': 4096},
        {'key': 'On3', 'expected': 'O(n^3)', 'source': 'reference:CODE-P23',
         'title': '立方：石子合并区间 DP（参考解）', 'code': 'CODE-P23'},
    ]
    for group in groups:
        if 'code' in group:
            code = group['code']
            group['program'] = reference_python(bank, code)
            family, spec = profiles.PROFILES[code]
            spec = dict(spec)
            if group.get('max_n_override'):
                spec['max_n'] = group['max_n_override']
            group['family'] = family
            group['spec'] = spec
            group['profile_code'] = code
    return groups


def run_complexity_group(bank: dict[str, dict], group: dict, workdir: pathlib.Path,
                         *, seed: int, wall_limit_ms: int, budget_ms: int,
                         repeats: int, max_rungs: int) -> dict:
    source = group['program']
    static = complexity.analyze_static(source, 'python3')
    verification = {'ok': None, 'cases': 0}
    if 'code' in group:
        verification = verify_equivalent(bank, group['code'], source, source, workdir,
                                         limit=len(bank[group['code']].get('tests') or []))
    started = time.perf_counter()
    outcomes, stop_reason = probe.escalating_measure(
        source, 'python3', group['family'], group['spec'], seed=seed,
        wall_limit_ms=wall_limit_ms, budget_ms=budget_ms, repeats=repeats, max_rungs=max_rungs)
    elapsed = time.perf_counter() - started
    measurements = [complexity.Measurement(n=outcome.n, wall_ms=outcome.median_ms,
                                          adjusted_ms=outcome.median_ms,
                                          peak_rss_kib=outcome.peak_rss_kib,
                                          verdict=outcome.verdict,
                                          repeats=len(outcome.walls_ms))
                    for outcome in outcomes]
    reference = {outcome.n: outcome.reference_ms for outcome in outcomes
                 if outcome.reference_ms is not None}
    conclusion = complexity.classify_growth(measurements, reference)
    summary = complexity.combine(static, conclusion)
    payload = conclusion.to_payload()
    rungs = [outcome.to_payload() for outcome in outcomes]
    return {
        'key': group['key'],
        'title': group['title'],
        'expected_class': group['expected'],
        'source': group['source'],
        'profile': {'family': group['family'], 'spec': group['spec']},
        'parameters': {'seed': seed, 'wall_limit_ms': wall_limit_ms,
                       'budget_ms': budget_ms, 'repeats': repeats, 'max_rungs': max_rungs},
        'reference_solution_verification': verification,
        'static': {'time_class': static.time_class, 'space_class': static.space_class,
                   'confidence': static.confidence, 'loop_depth': static.loop_depth,
                   'recursive': static.recursive, 'sorts': static.sorts,
                   'evidence': static.evidence, 'notes': static.notes},
        'stop_reason': stop_reason,
        'elapsed_seconds': round(elapsed, 2),
        'rungs': rungs,
        'conclusion': {'measured_class': payload['measured_class'],
                       'io_class': payload['io_class'],
                       'informative': payload['informative'],
                       'r2': payload['r2'], 'exponent': payload['exponent'],
                       'confidence': payload['confidence'], 'floor_ms': payload['floor_ms'],
                       'coefficient': payload['fit']['coefficient'],
                       'fitted_class_from_fit': payload['fit']['fitted_class'],
                       'fit_r2': payload['fit']['r2'],
                       'fit_notes': payload['fit']['notes'],
                       'reference_fitted_class': (payload['reference_fit'] or {}).get('fitted_class'),
                       'reference_fit_r2': (payload['reference_fit'] or {}).get('r2'),
                       'reference_fit_confidence': (payload['reference_fit'] or {}).get('confidence')},
        'candidate_r2': candidate_r2(measurements, payload['fit']['fitted_class']),
        'final': {'time_class': summary['time']['class'],
                  'source': summary['time']['source'],
                  'confidence': summary['time']['confidence'],
                  'agreement': summary['time']['agreement'],
                  'space_class': summary['space']['class'],
                  'limitations': summary['limitations']},
        'agrees_with_expected': summary['time']['class'] == group['expected'],
    }


def candidate_r2(measurements: list[complexity.Measurement],
                 chosen: str) -> list[dict]:
    """R² of every candidate class on this ladder.

    The module picks the best R² among the classes admitted by the log-log slope
    filter, and breaks a near-tie in favour of the cheaper class. Printing the
    whole column makes that decision checkable: when two neighbouring classes
    differ by less than the 0.005 tie margin, the report can show it.
    """
    points = [item for item in measurements if item.verdict == 'OK' and item.wall_ms > 0]
    if len(points) < 2:
        return []
    times = [item.wall_ms for item in points]
    mean_time = sum(times) / len(times)
    total = sum((value - mean_time) ** 2 for value in times)
    rows = []
    for name in complexity.TIME_CLASSES:
        values = [complexity.GROWTH_FUNCTIONS[name](item.n) for item in points]
        coefficients = complexity._fit_with_offset(values, times)  # noqa: SLF001 - read-only diagnostic
        if coefficients is None:
            rows.append({'class': name, 'r2': None})
            continue
        a, b = coefficients
        residuals = [value - (a * basis + b) for value, basis in zip(times, values)]
        r2 = 1.0 if total <= 1e-12 else 1 - sum(residual * residual for residual in residuals) / total
        rows.append({'class': name, 'r2': round(max(0.0, min(1.0, r2)), 6),
                     'chosen': name == chosen})
    rows.sort(key=lambda row: (-1 if row['r2'] is None else row['r2']), reverse=True)
    return rows


def experiment_repeatability(bank: dict[str, dict], workdir: pathlib.Path,
                            keys: tuple[str, ...]) -> dict:
    """Run selected groups three times and record how the verdict moves.

    Wall-clock measurement on a shared machine is noisy; reporting a single run
    as if it were exact would overstate what the estimator can promise. Only the
    groups whose verdict was unstable in development are repeated, to keep the
    whole script inside the ten-minute budget.
    """
    groups = {group['key']: group for group in build_complexity_groups(bank)}
    rows = []
    for key in keys:
        group = groups[key]
        runs = []
        for attempt in range(3):
            block = run_complexity_group(
                bank, group, workdir, seed=SEED + 900 + attempt, wall_limit_ms=4000,
                budget_ms=60000, repeats=5, max_rungs=13)
            runs.append({
                'attempt': attempt + 1,
                'stop_reason': block['stop_reason'],
                'measured_class': block['conclusion']['measured_class'],
                'fit_r2': block['conclusion']['fit_r2'],
                'confidence': block['conclusion']['confidence'],
                'final_class': block['final']['time_class'],
                'final_source': block['final']['source'],
                'seconds': block['elapsed_seconds'],
                'rungs': [(rung['n'], rung['wall_ms']) for rung in block['rungs']],
            })
        measured = [run['measured_class'] for run in runs]
        finals = [run['final_class'] for run in runs]
        rows.append({
            'key': key,
            'expected': group['expected'],
            'title': group['title'],
            'runs': runs,
            'measured_classes': measured,
            'final_classes': finals,
            'measured_stable': len(set(measured)) == 1,
            'final_classification_correct_runs': sum(1 for value in finals
                                                     if value == group['expected']),
        })
    return {
        'name': '重复性：同一组被测程序连续测 3 次',
        'purpose': '量化墙钟测量的波动对最终类别的影响；报告正文里只写一次的数字必须带着这个前提读',
        'runs_per_group': 3,
        'rows': rows,
    }


# -------------------------------------------------------------------- report


def experiment_fit_noise_sensitivity(trials: int = 40) -> dict:
    """How often the fitter picks the truth when the same curve carries noise.

    The noiseless calibration in :func:`experiment_fit_calibration` shows the rule
    is internally consistent. This second view adds multiplicative noise of 2%, 5%
    and 10% to ideal ``t = b + a*f(n)`` curves and counts what the fitter reports.
    It is the evidence behind two claims in the report: a log factor becomes
    unreliable under noise, and the confidence level is not a promise of accuracy.

    Deterministic: the random source is seeded, so a rerun reproduces the table.
    """
    rng = random.Random(SEED + 17)
    sizes = (256, 512, 1024, 2048, 4096, 8192, 16384)
    classes = ('O(1)', 'O(log n)', 'O(n)', 'O(n log n)', 'O(n^2)', 'O(n^3)')
    floor_ms, amplitude_ms = 12.0, 24.0
    rows = []
    for sigma in (0.02, 0.05, 0.10):
        for ideal in classes:
            function = complexity.GROWTH_FUNCTIONS[ideal]
            base = function(sizes[0])
            reported: dict[str, int] = {}
            confident_wrong = 0
            for _ in range(trials):
                points = []
                for n in sizes:
                    wall = (floor_ms + amplitude_ms * function(n) / base) * (1 + rng.gauss(0, sigma))
                    points.append(complexity.Measurement(
                        n=n, wall_ms=wall, adjusted_ms=wall, peak_rss_kib=None, verdict='OK'))
                fit = complexity.fit_growth(points, floor_ms=floor_ms)
                reported[fit.fitted_class] = reported.get(fit.fitted_class, 0) + 1
                if fit.fitted_class != ideal and fit.confidence in ('MEDIUM', 'HIGH'):
                    confident_wrong += 1
            rows.append({
                'sigma': sigma, 'ideal_class': ideal, 'trials': trials,
                'reported': dict(sorted(reported.items())),
                'exact_hits': reported.get(ideal, 0),
                'accuracy': round(reported.get(ideal, 0) / trials, 3),
                'confident_wrong': confident_wrong,
            })
    return {
        'name': '拟合器噪声敏感性：理想曲线加乘性噪声后重复 40 次',
        'purpose': '量化“置信度 HIGH 不等于结论正确”，并给 log 因子在噪声下的不稳定程度一个可复现的数字',
        'parameters': {'sizes': list(sizes), 'floor_ms': floor_ms,
                       'amplitude_at_first_rung_ms': amplitude_ms,
                       'sigmas': [0.02, 0.05, 0.10], 'trials': trials, 'seed': SEED + 17},
        'rows': rows,
    }


def build_report(*, similarity_blocks: dict, complexity_blocks: list[dict],
                 calibration: dict, noise: dict, repeatability: dict,
                 wall_seconds: float) -> dict:
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
                '全部相似度来自 similarity.compare，复杂度来自 probe.escalating_measure '
                '+ complexity.classify_growth + complexity.combine，与线上路径一致',
                '耗时是对真实进程的墙钟测量，每次运行会有波动；结构、类别和指纹数与运行无关',
                '脚本不连接数据库、不读名册、不联网',
            ],
        },
        'similarity': similarity_blocks,
        'complexity': {'groups': complexity_blocks, 'fit_calibration': calibration,
                       'fit_noise_sensitivity': noise,
                       'repeatability': repeatability},
    }


def summary_line(report: dict) -> str:
    similarity_blocks = report['similarity']
    cosmetic = similarity_blocks['cosmetic']
    light = similarity_blocks['structural_light']
    heavy = similarity_blocks['structural_heavy']
    same_problem = similarity_blocks['unrelated_same_problem']
    cross = similarity_blocks['unrelated_cross_problem']
    scale = similarity_blocks['scale']
    scale_text = '/'.join(f"{row['seconds_median']:.2f}" for row in scale['rows'])
    complexity_text = ' '.join(f"{group['key']}:{group['final']['time_class']}"
                               for group in report['complexity']['groups'])
    agreed = sum(1 for group in report['complexity']['groups'] if group['agrees_with_expected'])
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
        f"scale(20/50/100/200)s={scale_text} exponent={scale['loglog_exponent']:.2f} "
        f"| complexity: {len(report['complexity']['groups'])} groups agree={agreed} {complexity_text}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=pathlib.Path,
                        help='把完整 JSON 报告写到这个路径（stdout 只保留汇总行）')
    arguments = parser.parse_args(argv)

    started = time.perf_counter()
    bank = load_bank()
    workdir = pathlib.Path(tempfile.mkdtemp(prefix='cx-experiment-'))

    similarity_blocks = {}
    similarity_blocks['cosmetic'] = experiment_cosmetic(bank, workdir)
    similarity_blocks['structural_light'] = experiment_structural_light(bank, workdir)
    similarity_blocks['structural_heavy'] = experiment_structural_heavy(bank, workdir)
    similarity_blocks['insertion_sensitivity'] = experiment_insertion_sensitivity(bank)
    similarity_blocks['unrelated_same_problem'] = experiment_unrelated_same_problem(bank, workdir)
    similarity_blocks['unrelated_cross_problem'] = experiment_unrelated_cross_problem(bank)
    similarity_blocks['scale'] = experiment_scale(bank)
    similarity_blocks['honest_baseline'] = experiment_honest_baseline()

    complexity_blocks = []
    for index, group in enumerate(build_complexity_groups(bank)):
        complexity_blocks.append(run_complexity_group(
            bank, group, workdir, seed=SEED + index, wall_limit_ms=4000, budget_ms=60000,
            repeats=5, max_rungs=13))
    calibration = experiment_fit_calibration(bank)
    noise = experiment_fit_noise_sensitivity()
    repeatability = experiment_repeatability(bank, workdir, ('Olog', 'Onlog'))

    report = build_report(similarity_blocks=similarity_blocks,
                          complexity_blocks=complexity_blocks,
                          calibration=calibration,
                          noise=noise,
                          repeatability=repeatability,
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
