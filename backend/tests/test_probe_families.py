"""Tests for the input-synthesis families that give problems a scalable input.

Two properties matter for every generator. The same family, seed and spec must
produce byte-identical text, because a stored report has to be reproducible
later. And the generated text must be readable by the problem's own reference
solution: a format mismatch would measure the program's error path instead of
its algorithm, which is exactly the bug this table was rewritten to remove.

The reference-solution cases run a single rung each on purpose; the whole file
stays in the low seconds. Full 70-problem acceptance is the offline script
``scripts/validate_complexity_profiles.py``.
"""
import json
import time

import pytest

from app.analysis import probe
from app.analysis.profiles import NOT_SCALABLE, PROFILES, QUESTION_BANK
from app.analysis.trace.adapters import python_adapter

SEED = 20261028

# Families added (or given new spec options) when the route switched to counted
# execution traces. Each one describes a concrete input format read by the bank's
# own reference solutions.
COVERAGE_FAMILIES = (
    'THREE_INTS', 'INT_ARRAY_WITH_K', 'SORTED_ARRAY_QUERIES',
    'INT_ARRAY_OPERATIONS', 'TWO_INT_ARRAYS', 'INT_ARRAY_ROWS_TWO_HEADER',
    'GRAPH_TREE_QUERIES', 'GRAPH_EDGE_QUERIES', 'GRAPH_COLORING',
    'BIG_TWO_STRINGS', 'STRING_LIST', 'STRING_RANGE_QUERIES',
    'POSTFIX_EXPRESSION', 'STACK_OPERATIONS', 'GRID_WITH_WORD',
    'TRIANGLE_ROWS', 'KNAPSACK',
)

# One representative problem per tricky format: values spread over the triangle
# rows, the separate query-count line, a simple graph with u < v, a string
# followed by position queries, alternating update/query operations, and range
# rows where l <= r matters.
REFERENCE_CASES = ('CODE-P20', 'CODE-P32', 'CODE-P38', 'CODE-P45', 'CODE-P54', 'CODE-P70')

BANK = {entry['code']: entry.get('reference_solutions') or []
        for entry in json.loads(QUESTION_BANK.read_text(encoding='utf-8'))}


def _sample_spec(family: str) -> dict:
    """The spec the seeded profiles use for this family (first problem wins)."""
    for candidate, spec in PROFILES.values():
        if candidate == family:
            return dict(spec)
    raise AssertionError(f'{family} 没有对应的种子伸缩档，无法取样')


def test_every_profile_names_a_known_family():
    assert all(family in probe.FAMILIES for family, _ in PROFILES.values())
    assert all(code in BANK for code in PROFILES)
    # A code listed as not scalable has to carry the family that says so.
    assert all(PROFILES[code][0] == 'FIXED' for code in NOT_SCALABLE)
    assert all(code in PROFILES for code in NOT_SCALABLE)


@pytest.mark.parametrize('family', COVERAGE_FAMILIES)
def test_generation_is_deterministic(family):
    spec = _sample_spec(family)
    first = probe.generate(family, 64, SEED, spec)
    second = probe.generate(family, 64, SEED, spec)
    assert first
    assert first == second
    assert probe.generate(family, 64, SEED + 1, spec) == probe.generate(family, 64, SEED + 1, spec)


@pytest.mark.parametrize('family', COVERAGE_FAMILIES)
def test_ladder_is_reproducible(family):
    spec = _sample_spec(family)
    first = probe.ladder(family, SEED, spec)
    second = probe.ladder(family, SEED, spec)
    assert len(first) >= 3
    assert [(rung.n, rung.input_text) for rung in first] == \
           [(rung.n, rung.input_text) for rung in second]
    assert [rung.n for rung in first] == sorted(rung.n for rung in first)


@pytest.mark.parametrize('family', COVERAGE_FAMILIES)
def test_ladder_shrinks_with_max_n(family):
    spec = _sample_spec(family)
    limit = int(spec.get('max_n', 4096))
    if limit <= 32:
        pytest.skip('该题种子的 max_n 已在最小档附近')
    # The ladder stops at the doubling cap (4096), so a smaller max_n has to be
    # expressed below that cap to observe the shrink.
    target = min(limit // 4, 1024)
    full = probe.ladder(family, SEED, spec)
    reduced = probe.ladder(family, SEED, {**spec, 'max_n': target})
    assert full[-1].n <= limit
    assert reduced
    assert all(rung.n <= target for rung in reduced)
    assert reduced[-1].n < full[-1].n


def _reference_source(code: str) -> str:
    for solution in BANK[code]:
        if solution.get('language') == 'Python':
            return solution['content']
    raise AssertionError(f'{code} 没有 Python 参考解')


@pytest.mark.parametrize('code', REFERENCE_CASES)
def test_reference_solution_accepts_smallest_rung(code, judge_work_root):
    family, spec = PROFILES[code]
    rungs = probe.ladder(family, SEED, spec)
    assert len(rungs) >= 3
    trace = python_adapter.collect(_reference_source(code), [rungs[0]],
                                   deadline=time.monotonic() + 10, seed=SEED)
    assert trace.points, trace.notes
    point = trace.points[0]
    assert point.verdict == 'OK', point.detail
    assert point.work > 0


# Independent synthetic problems supplied by a gpt-6-luna subagent. They have no
# CODE-Pxx mapping and their references assert the declared input constraints.
ADAPTIVE_EXAMPLES = (
    ('NEW-MAX', '第一行输入整数 n，第二行输入 n 个整数。',
     '1 ≤ n ≤ 1000；-10^9 ≤ a_i ≤ 10^9', '5\n-8 3 -2 7 1\n', '7\n',
     '''import sys
t=list(map(int,sys.stdin.read().split())); n=t[0]; a=t[1:]
assert 1<=n<=1000 and len(a)==n
assert all(-10**9<=x<=10**9 for x in a)
print(max(a))
''', 'INT_ARRAY'),
    ('NEW-RANK', '第一行输入 n k，第二行输入 n 个整数。',
     '1 ≤ k ≤ n ≤ 1000；-10^9 ≤ a_i ≤ 10^9', '5 2\n4 9 1 9 3\n', '9\n',
     '''import sys
t=list(map(int,sys.stdin.read().split())); n,k=t[:2]; a=t[2:]
assert 1<=k<=n<=1000 and len(a)==n
assert all(-10**9<=x<=10**9 for x in a)
print(sorted(a,reverse=True)[k-1])
''', 'INT_ARRAY_WITH_K'),
    ('NEW-SORTED', '第一行输入 n x，第二行输入一个非递减数组，包含 n 个整数。',
     '1 ≤ n ≤ 1000；-10^9 ≤ x, a_i ≤ 10^9；数组必须非递减。', '6 4\n-2 0 4 4 5 9\n', '4\n',
     '''import sys
t=list(map(int,sys.stdin.read().split())); n,x=t[:2]; a=t[2:]
assert 1<=n<=1000 and len(a)==n and -10**9<=x<=10**9
assert all(-10**9<=v<=10**9 for v in a) and a==sorted(a)
print(sum(v<=x for v in a))
''', 'INT_ARRAY_WITH_K'),
    ('NEW-MATRIX', '第一行输入行数 n 和列数 m，随后输入 n 行，每行 m 个整数。',
     '1 ≤ n, m ≤ 100；-10^6 ≤ a_ij ≤ 10^6', '2 3\n1 -2 3\n4 5 -6\n', '5\n',
     '''import sys
t=list(map(int,sys.stdin.read().split())); n,m=t[:2]; a=t[2:]
assert 1<=n<=100 and 1<=m<=100 and len(a)==n*m
assert all(-10**6<=v<=10**6 for v in a)
print(sum(a))
''', 'MATRIX'),
    ('NEW-GRAPH', '输入无向连通简单图。第一行输入顶点数 n 和边数 m，随后 m 行每行输入 u v。',
     '1 ≤ n ≤ 1000；图连通、无自环、无重边；n-1 ≤ m ≤ n(n-1)/2；端点在 [1,n]。',
     '4 3\n1 2\n2 3\n3 4\n', '1\n',
     '''import sys
t=list(map(int,sys.stdin.read().split())); n,m=t[:2]
assert 1<=n<=1000 and n-1<=m<=n*(n-1)//2 and len(t)==2+2*m
adj=[set() for _ in range(n+1)]; seen=set()
for i in range(m):
 u,v=t[2+2*i:4+2*i]; e=(min(u,v),max(u,v))
 assert 1<=u<=n and 1<=v<=n and u!=v and e not in seen
 seen.add(e); adj[u].add(v); adj[v].add(u)
reached={1}; pending=[1]
while pending:
 for v in adj[pending.pop()]:
  if v not in reached: reached.add(v); pending.append(v)
assert len(reached)==n
print(len(adj[1]))
''', 'GRAPH_EDGES'),
    ('NEW-STRING', '输入一个仅含小写英文字母的非空字符串。',
     '字符串长度 1 ≤ |s| ≤ 10000；字符仅为 a 至 z。', 'algorithm\n', '3\n',
     '''import sys
lines=sys.stdin.read().splitlines(); assert len(lines)==1
s=lines[0]; assert 1<=len(s)<=10000 and all('a'<=c<='z' for c in s)
print(sum(c in "aeiou" for c in s))
''', 'ONE_STRING'),
    ('NEW-PREFIX', '输入两行字符串，均仅含小写英文字母。',
     '两个字符串长度均在 1 至 1000 之间；字符仅为 a 至 z。', 'flower\nflow\n', 'flow\n',
     '''import sys
lines=sys.stdin.read().splitlines(); assert len(lines)==2
a,b=lines; assert 1<=len(a)<=1000 and 1<=len(b)<=1000
assert all('a'<=c<='z' for c in a+b)
i=0
while i<min(len(a),len(b)) and a[i]==b[i]: i+=1
print(a[:i] if i else '-')
''', 'TWO_STRINGS'),
    ('NEW-CONSTANT', '输入一个非负整数 n。', '0 ≤ n ≤ 10^9', '10\n', '55\n',
     '''import sys
t=list(map(int,sys.stdin.read().split())); assert len(t)==1
n=t[0]; assert 0<=n<=10**9
print(n*(n+1)//2)
''', 'SINGLE_INT'),
)


# Additional independent formats supplied by the same gpt-6-luna data workflow.
ADAPTIVE_EXAMPLES += (
    ('EXT-POW', '单行三个整数 a b p，计算 a^b mod p。',
     '0<=a<=10^9；0<=b<=10^18；2<=p<=1000000007', '2 10 13\n', '10\n',
     '''import sys
rows=sys.stdin.read().splitlines(); assert len(rows)==1
a,b,p=map(int,rows[0].split())
assert 0<=a<=10**9 and 0<=b<=10**18 and 2<=p<=1000000007
print(pow(a,b,p))
''', 'THREE_INTS'),
    ('EXT-ARRAY-DIST', '第一行整数 n；第二、三行分别为含 n 个整数的数组 A、B。',
     '1<=n<=1000；0<=A[i]<=100；-100<=B[i]<=100；sum(A)<=10000 且 sum(B)<=10000',
     '3\n2 5 1\n4 -2 2\n', '10\n',
     '''import sys
rows=sys.stdin.read().splitlines(); assert len(rows)==3
n=int(rows[0]); A=list(map(int,rows[1].split())); B=list(map(int,rows[2].split()))
assert 1<=n<=1000 and len(A)==len(B)==n
assert all(0<=x<=100 for x in A) and all(-100<=x<=100 for x in B)
assert sum(A)<=10000 and sum(B)<=10000
print(sum(abs(x-y) for x,y in zip(A,B)))
''', 'TWO_INT_ARRAYS'),
    ('EXT-KNAPSACK', '第一行 n W，接下来 n 行各有一个物品的 weight value。',
     '1<=n<=200；0<=W<=10000；1<=weight<=20000；0<=value<=1000000；重量允许大于容量。',
     '3 7\n4 5\n5 8\n2 3\n', '11\n',
     '''import sys
rows=sys.stdin.read().splitlines(); n,W=map(int,rows[0].split())
assert 1<=n<=200 and 0<=W<=10000 and len(rows)==n+1
dp=[0]*(W+1)
for row in rows[1:]:
 w,v=map(int,row.split()); assert 1<=w<=20000 and 0<=v<=1000000
 for j in range(W,w-1,-1): dp[j]=max(dp[j],dp[j-w]+v)
print(max(dp))
''', 'INT_ARRAY_ROWS_TWO_HEADER'),
    ('EXT-SEARCH-COUNT', '第一行 n q；第二行是非降序数组；接下来 q 行各一个查询值。',
     '1<=n,q<=100000；数组和查询值均在 -1000000000..1000000000。',
     '6 3\n1 2 2 2 5 9\n2\n4\n9\n', '3\n0\n1\n',
     '''import sys,bisect
rows=sys.stdin.read().splitlines(); n,q=map(int,rows[0].split()); a=list(map(int,rows[1].split()))
assert 1<=n<=100000 and 1<=q<=100000 and len(a)==n and len(rows)==q+2
assert a==sorted(a) and all(-10**9<=x<=10**9 for x in a)
for row in rows[2:]:
 x=int(row); assert -10**9<=x<=10**9
 print(bisect.bisect_right(a,x)-bisect.bisect_left(a,x))
''', 'SORTED_ARRAY_QUERIES'),
    ('EXT-TRIANGLE', '第一行是层数 n；随后第 i 行有 i 个整数。',
     '1<=n<=1000；-1000000<=a[i][j]<=1000000', '3\n2\n4 1\n1 2 7\n', '10\n',
     '''import sys
rows=sys.stdin.read().splitlines(); n=int(rows[0]); assert 1<=n<=1000 and len(rows)==n+1
a=[list(map(int,row.split())) for row in rows[1:]]
assert all(len(row)==i+1 and all(-10**6<=x<=10**6 for x in row) for i,row in enumerate(a))
d=a[-1][:]
for i in range(n-2,-1,-1): d=[a[i][j]+max(d[j],d[j+1]) for j in range(i+1)]
print(d[0])
''', 'TRIANGLE_ROWS'),
    ('EXT-GRID-PATH', '第一行 n m，接下来 n 行各含 m 个字符。`.` 表示可走，`#` 表示障碍。',
     '1<=n,m<=1000；n*m<=1000000；字符仅为 . 或 #；左上角和右下角必须为 .。',
     '3 4\n...#\n.#..\n....\n', '5\n',
     '''import sys
from collections import deque
rows=sys.stdin.read().splitlines(); n,m=map(int,rows[0].split()); a=rows[1:]
assert 1<=n<=1000 and 1<=m<=1000 and n*m<=10**6 and len(a)==n
assert all(len(row)==m and set(row)<={'.','#'} for row in a) and a[0][0]==a[-1][-1]=='.'
d=[[-1]*m for _ in range(n)];d[0][0]=0;q=deque([(0,0)])
while q:
 x,y=q.popleft()
 for r,c in ((x-1,y),(x+1,y),(x,y-1),(x,y+1)):
  if 0<=r<n and 0<=c<m and a[r][c]=='.' and d[r][c]<0:
   d[r][c]=d[x][y]+1;q.append((r,c))
print(d[-1][-1])
''', 'GRID'),
    ('EXT-BIG-ADD', '两行分别给出一个十进制非负整数，输出它们的和。',
     '每个字符串满足 1<=len(s)<=1000；仅含 ASCII 数字；除字符串 0 外不得有前导零。',
     '999999999999999999\n1\n', '1000000000000000000\n',
     '''import sys
rows=sys.stdin.read().splitlines(); assert len(rows)==2
for s in rows:
 assert 1<=len(s)<=1000 and s.isascii() and s.isdigit() and (len(s)==1 or s[0]!='0')
print(int(rows[0])+int(rows[1]))
''', 'BIG_TWO_STRINGS'),
    ('EXT-STRING-SORT', '第一行整数 n，接下来 n 行各一个字符串。按字典序升序输出，重复项保留。',
     '1<=n<=10000；每个字符串满足 1<=len(s)<=1000，仅含小写英文字母；字符串总长度不超过 1000000。',
     '3\ncat\napple\nbee\n', 'apple\nbee\ncat\n',
     '''import sys
rows=sys.stdin.read().splitlines(); n=int(rows[0]); a=rows[1:]
assert 1<=n<=10000 and len(a)==n and sum(map(len,a))<=10**6
assert all(1<=len(s)<=1000 and all('a'<=c<='z' for c in s) for s in a)
print('\\n'.join(sorted(a)))
''', 'STRING_LIST'),
)


def _adaptive_example(example):
    from types import SimpleNamespace
    code, description, constraints, text, expected, source, family = example
    version = SimpleNamespace(input_spec_md=description, data_constraints_md=constraints)
    return version, [(text, expected)], source, family


@pytest.mark.parametrize('example', ADAPTIVE_EXAMPLES, ids=lambda example: example[0])
def test_adaptive_inference_uses_new_problem_structure_and_constraints(example):
    from app.analysis.profiles import adaptive_candidates
    version, cases, _, family = _adaptive_example(example)
    candidates, reason = adaptive_candidates(version, cases)
    assert candidates, reason
    assert candidates[0]['family'] == family
    spec = candidates[0]['spec']
    for distribution in spec.get('distributions', ['random']):
        current = dict(spec, distribution=distribution)
        for size in spec['sizes']:
            text = probe.generate(family, size, SEED, current)
            probe.validate_input(family, text, current, size=size)
            assert text == probe.generate(family, size, SEED, current)


@pytest.mark.parametrize('example', ADAPTIVE_EXAMPLES, ids=lambda example: example[0])
def test_adaptive_reference_and_student_check_real_generated_inputs(example, judge_work_root):
    from app.analysis.profiles import adaptive_candidates, check_adaptive_submission, validate_adaptive
    version, cases, source, family = _adaptive_example(example)
    candidates, reason = adaptive_candidates(version, cases)
    assert candidates, reason
    spec, reason = validate_adaptive(candidates[0], [('python3', source)], cases)
    assert spec, reason
    assert len(spec['sizes']) >= 3
    assert spec['validation']['outputs']
    checked, reason = check_adaptive_submission(source, 'python3', family, spec)
    assert checked, reason


@pytest.mark.parametrize(('description', 'constraints', 'sample'), (
    ('输入一组数，输出平均值。', '', '1 2 3\n'),
    ('读入若干行直到 EOF。', '每行一个整数。', '1\n2\n'),
    ('输入一棵树。', '1 <= n <= 1000', '3\n1 2\n2 3\n'),
    ('第一行 n，第二行 n 个整数。', '1<=n<=100；1<=a_i<=100；每个元素必须为质数', '3\n2 3 5\n'),
))
def test_adaptive_inference_rejects_ambiguous_or_unsupported_domains(description, constraints, sample):
    from types import SimpleNamespace
    from app.analysis.profiles import adaptive_candidates
    candidates, reason = adaptive_candidates(SimpleNamespace(input_spec_md=description,
        data_constraints_md=constraints), [(sample, '0\n')])
    assert candidates == [] and reason


def test_adaptive_validation_rejects_wrong_reference_and_wrong_student(judge_work_root):
    from app.analysis.profiles import adaptive_candidates, check_adaptive_submission, validate_adaptive
    version, cases, source, family = _adaptive_example(ADAPTIVE_EXAMPLES[0])
    candidate = adaptive_candidates(version, cases)[0][0]
    spec, reason = validate_adaptive(candidate, [('python3', 'print(999)')], cases)
    assert spec is None and '已有测试用例' in reason
    spec, reason = validate_adaptive(candidate, [('python3', source)], cases)
    assert spec, reason
    checked, reason = check_adaptive_submission('print(999)', 'python3', family, spec)
    assert checked is None and '原评测结果不变' in reason


def test_input_validation_rejects_wrong_count_order_and_graph_connectivity():
    from app.analysis.profiles import adaptive_candidates
    for example, invalid in ((ADAPTIVE_EXAMPLES[0], '3\n1 2\n'),
                             (ADAPTIVE_EXAMPLES[2], '3 4\n3 1 2\n'),
                             (ADAPTIVE_EXAMPLES[4], '4 3\n1 2\n2 3\n1 3\n')):
        version, cases, _, family = _adaptive_example(example)
        candidate = adaptive_candidates(version, cases)[0][0]
        with pytest.raises(probe.ProfileError):
            probe.validate_input(family, invalid, candidate['spec'])


def test_profile_validation_accepts_constant_reference_work(monkeypatch):
    from types import SimpleNamespace
    from app.analysis.profiles import validate_profile
    from app.analysis.trace import collect
    point = SimpleNamespace(verdict='OK', work=10)
    trace = SimpleNamespace(points=[point] * 4, ok_points=[point] * 4, stop_reason='OK')
    monkeypatch.setattr(collect, 'collect', lambda *args, **kwargs: trace)
    assert validate_profile({'NEW': [{'language': 'Python', 'content': 'print(1)'}]},
                            'NEW', 'SINGLE_INT', {'max_n': 4096}) == (True, '')


def test_adaptive_numeric_constraints_preserve_zero_absolute_bounds_and_descending_order():
    from types import SimpleNamespace
    from app.analysis.profiles import adaptive_candidates
    version = SimpleNamespace(input_spec_md='第一行 n，第二行 n 个整数，数组必须非递增。',
                              data_constraints_md='1<=n<=100；|a_i|<=10^6')
    candidate = adaptive_candidates(version, [('3\n5 0 -2\n', '0')])[0][0]
    spec = candidate['spec']
    assert spec['value_min'] == -10**6 and spec['value_max'] == 10**6
    assert spec['order'] == 'descending' and spec['distributions'] == ['descending']
    text = probe.generate(candidate['family'], 16, SEED, spec)
    probe.validate_input(candidate['family'], text, spec, size=16)
    version, _, _, _ = _adaptive_example(ADAPTIVE_EXAMPLES[7])
    candidates, reason = adaptive_candidates(version, [('0\n', '0\n')])
    assert candidates, reason


def test_adaptive_ordered_rows_keep_both_independent_column_bounds():
    from types import SimpleNamespace
    from app.analysis.profiles import adaptive_candidates
    version = SimpleNamespace(input_spec_md='第一行 n，之后 n 行，每行两个整数 s_i 和 t_i。',
                              data_constraints_md='1<=n<=100；0<=s_i<=5；10<=t_i<=20；s_i<t_i')
    candidate = adaptive_candidates(version, [('2\n0 10\n5 20\n', '0')])[0][0]
    text = probe.generate(candidate['family'], 64, SEED, candidate['spec'])
    for line in text.splitlines()[1:]:
        start, end = map(int, line.split())
        assert 0 <= start <= 5 and 10 <= end <= 20


def test_adaptive_reference_timeout_caps_sizes_instead_of_rejecting_valid_inputs(judge_work_root, monkeypatch):
    from app.analysis.profiles import adaptive_candidates, validate_adaptive
    from app.judge import local
    version, cases, source, _ = _adaptive_example(ADAPTIVE_EXAMPLES[7])
    original, calls = local._run_case, []
    def limited(command, directory, data, *args, **kwargs):
        calls.append(data)
        if len(calls) > 1 and int(data) >= 8:
            return 'TIME_LIMIT_EXCEEDED', b'', 1000
        return original(command, directory, data, *args, **kwargs)
    monkeypatch.setattr(local, '_run_case', limited)
    candidate = adaptive_candidates(version, cases)[0][0]
    spec, reason = validate_adaptive(candidate, [('python3', source)], cases)
    assert spec, reason
    assert spec['sizes'] == [1, 2, 4]


def test_adaptive_reference_supports_a_cpp_database_reference(judge_work_root):
    from app.analysis.profiles import adaptive_candidates, validate_adaptive
    from app.judge import config
    if config.toolchain('cpp') is None:
        pytest.skip('本机没有 C++ 工具链')
    version, cases, _, _ = _adaptive_example(ADAPTIVE_EXAMPLES[0])
    source = '''#include <cstdio>
int main(){int n,x,b=-1000000000; if(scanf("%d",&n)!=1)return 1;
for(int i=0;i<n;++i){if(scanf("%d",&x)!=1)return 1;if(x>b)b=x;}printf("%d\\n",b);}
'''
    spec, reason = validate_adaptive(adaptive_candidates(version, cases)[0][0], [('C++', source)], cases)
    assert spec, reason
    assert spec['validation']['reference_language'] == 'cpp'


def test_string_character_set_is_not_inferred_from_digits_in_length_bounds():
    from types import SimpleNamespace
    from app.analysis.profiles import adaptive_candidates
    version = SimpleNamespace(input_spec_md='输入两行仅含小写字母的字符串。',
                              data_constraints_md='1<=|s|<=1000；1<=|t|<=1000')
    candidates, reason = adaptive_candidates(version, [('flower\nflow\n', 'flow\n')])
    assert candidates, reason
    assert candidates[0]['spec']['alphabet'] == 'abcdefghijklmnopqrstuvwxyz'


@pytest.mark.parametrize(('description', 'constraints', 'text'), (
    ('单行三个整数 a b p。', '0<=a<=100；0<=b<=100；2<=p<=100；p 必须为质数。', '2 3 5\n'),
    ('第一行 n；第二、三行分别是数组 A 和 B，每行 n 个整数。',
     '1<=n<=100；0<=A[i],B[i]<=100；两数组元素和必须相等。', '2\n1 2\n2 1\n'),
    ('第一行 n，第二行 n 个整数 a_i。', '1<=n<=100；0<=a_i<=10；数组元素之和必须等于 10。', '2\n5 5\n'),
    ('第一行 n m，第二行 n 个整数 a_i。', '1<=n,m<=100；0<=a_i<=10000；a_i<=n*m。', '2 3\n1 2\n'),
    ('第一行 n，第二行 n 个整数。', '1<=n<=100；0<=a_i<=10；n 必须为奇数。', '3\n1 2 3\n'),
    ('第一行 n m，之后 m 行每行两个整数 u v，表示无向边。',
     '1<=n<=100；0<=m<=100；1<=u,v<=n；m<=n(n-1)/4', '4 1\n1 2\n'),
))
def test_unsupported_semantics_are_rejected_instead_of_silently_dropped(description, constraints, text):
    from types import SimpleNamespace
    from app.analysis.profiles import adaptive_candidates
    result, reason = adaptive_candidates(SimpleNamespace(input_spec_md=description,
        data_constraints_md=constraints), [(text, '0\n')])
    assert not result and reason


def test_layout_enforces_actual_parameter_bounds_instead_of_only_global_bounds():
    from types import SimpleNamespace
    from app.analysis.profiles import adaptive_candidates
    version = SimpleNamespace(input_spec_md='第一行 n，第二行 n 个整数 a_i。',
                              data_constraints_md='1<=n<=1000；1<=a_i<=n')
    candidate = adaptive_candidates(version, [('3\n1 2 3\n', '0')])[0][0]
    for n in (1, 4, 32):
        text = probe.generate(candidate['family'], n, SEED, candidate['spec'])
        assert all(1 <= value <= n for value in map(int, text.splitlines()[1].split()))
    with pytest.raises(probe.ProfileError):
        probe.validate_input(candidate['family'], '3\n1 2 4\n', candidate['spec'])


def test_layout_checks_both_array_sum_limits_and_grid_endpoints():
    from app.analysis.profiles import adaptive_candidates
    version, cases, _, family = _adaptive_example(ADAPTIVE_EXAMPLES[9])
    candidate = adaptive_candidates(version, cases)[0][0]
    text = '101\n' + ' '.join(['100'] * 101) + '\n' + ' '.join(['0'] * 101) + '\n'
    with pytest.raises(probe.ProfileError, match='和超出'):
        probe.validate_input(family, text, candidate['spec'])
    version, cases, _, family = _adaptive_example(ADAPTIVE_EXAMPLES[13])
    candidate = adaptive_candidates(version, cases)[0][0]
    with pytest.raises(probe.ProfileError, match='端点'):
        probe.validate_input(family, '2 2\n#.\n..\n', candidate['spec'])
    with pytest.raises(probe.ProfileError, match='字符集'):
        probe.validate_input(family, '2 2\n.X\n..\n', candidate['spec'])


def test_layout_checks_string_totals_and_leading_zeroes():
    from types import SimpleNamespace
    from app.analysis.profiles import adaptive_candidates
    version = SimpleNamespace(input_spec_md='第一行 n，接下来 n 行各一个小写字符串。',
        data_constraints_md='1<=n<=10；1<=len(s)<=10；字符串总长度不超过 5')
    candidate = adaptive_candidates(version, [('2\na\nb\n', '0')])[0][0]
    with pytest.raises(probe.ProfileError, match='总长度'):
        probe.validate_input(candidate['family'], '2\nabc\ndef\n', candidate['spec'])
    version, cases, _, family = _adaptive_example(ADAPTIVE_EXAMPLES[14])
    candidate = adaptive_candidates(version, cases)[0][0]
    with pytest.raises(probe.ProfileError, match='前导零'):
        probe.validate_input(family, '001\n2\n', candidate['spec'])


def test_capacity_scenario_exercises_feasible_items_without_changing_the_domain():
    from app.analysis.profiles import adaptive_candidates
    version, cases, _, family = _adaptive_example(ADAPTIVE_EXAMPLES[10])
    spec = adaptive_candidates(version, cases)[0][0]['spec']
    assert 'within_capacity' in spec['distributions']
    text = probe.generate(family, 32, SEED, dict(spec, distribution='within_capacity'))
    rows = [list(map(int, line.split())) for line in text.splitlines()]
    assert rows[0] == [32, 7]
    assert all(1 <= row[0] <= 7 for row in rows[1:])
    # Larger weights remain legal for the normal distribution and stored cases.
    probe.validate_input(family, '1 7\n20000 1\n', spec)


def test_equal_sample_header_values_do_not_hide_the_declared_record_count():
    from types import SimpleNamespace
    from app.analysis.profiles import adaptive_candidates
    version = SimpleNamespace(input_spec_md='第一行 n m，接下来 m 行每行两个整数 l r。',
        data_constraints_md='1<=n,m<=100；0<=l<=r<=100')
    candidates, reason = adaptive_candidates(version, [('3 3\n0 1\n2 3\n4 5\n', '0')])
    assert candidates, reason
    candidate = candidates[0]
    text = probe.generate(candidate['family'], 8, SEED, candidate['spec'])
    assert text.splitlines()[0] == '3 8'
    assert len(text.splitlines()) == 9
    probe.validate_input(candidate['family'], text, candidate['spec'], size=8)


def test_constraint_parser_does_not_join_separate_inequalities_or_truncate_products():
    from app.analysis.profiles import BOUND_INFINITY, _bounds, _normalise
    bounds = _bounds(_normalise('1<=n<=1000；1<=x<=n, |v|<=10^9'))
    assert bounds['n'] == (1, 1000)
    assert bounds['v'] == (-10**9, 10**9)
    bounds = _bounds(_normalise('1<=n,m<=6；1<=len(word)<=n * m<=36'))
    assert bounds['len_word'][1] == BOUND_INFINITY
    assert bounds['m'] == (1, 6)
    assert probe.bound_value('2^60') == 2**60
    assert probe.bound_value('2^31-1') == 2**31-1
    for expression in ("__import__('os')", '2^100000', 'a.real'):
        with pytest.raises((probe.ProfileError, KeyError)):
            probe.bound_value(expression)


def test_matrix_product_constraint_is_checked_for_generated_and_existing_inputs():
    from types import SimpleNamespace
    from app.analysis.profiles import adaptive_candidates
    version = SimpleNamespace(input_spec_md='第一行 n m，随后 n 行每行 m 个整数，表示矩阵。',
        data_constraints_md='1<=n,m<=100；0<=a_i<=10；n*m<=9')
    result, reason = adaptive_candidates(version, [('2 2\n1 2\n3 4\n', '0')])
    assert result, reason
    assert max(result[0]['spec']['sizes']) <= 3
    with pytest.raises(probe.ProfileError):
        probe.validate_input('MATRIX', '2 5\n1 2 3 4 5\n1 2 3 4 5\n', result[0]['spec'])
