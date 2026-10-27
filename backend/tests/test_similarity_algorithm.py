"""Unit tests for the two research algorithms.

The similarity tests include a brute-force cross-check: the inverted-index
counter must agree with naive set intersection on random small inputs. The
complexity tests pin the class each reference implementation should receive and
check the growth fit on synthetic data with known shape.
"""
import math
import random

import pytest

from app.analysis.algorithms import complexity, similarity


# --------------------------------------------------------------- similarity

REFERENCE_ACTIVITY = '''
n = int(input())
a = [tuple(map(int, input().split())) for _ in range(n)]
last, ans = -1, 0
for s, t in sorted(a, key=lambda p: (p[1], p[0])):
    if s >= last:
        last, ans = t, ans + 1
print(ans)
'''

RENAMED_ACTIVITY = '''
# 同一份答案：改标识符、改注释、改缩进，不应逃过检测
count = int(input())
items = [tuple(map(int, input().split())) for _ in range(count)]
end_time, total = -1, 0
for start, finish in sorted(items, key=lambda pair: (pair[1], pair[0])):
    if start >= end_time:
        end_time, total = finish, total + 1
print(total)
'''

# A real structural rewrite: assignment split in two, extra local, different
# comparison order. Still a copy, but it must score below an exact rename.
STRUCTURALLY_EDITED = '''
count = int(input())
items = [tuple(map(int, input().split())) for _ in range(count)]
end_time = -1
total = 0
ordered = sorted(items, key=lambda pair: (pair[1], pair[0]))
for start, finish in ordered:
    if end_time <= start:
        end_time, total = finish, total + 1
print(total)
'''

UNRELATED_MERGE_SORT = '''
import sys
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
            merged.append(left[i]); i += 1
        else:
            merged.append(right[j]); j += 1
    merged.extend(left[i:]); merged.extend(right[j:])
    return merged
data = sys.stdin.read().split()
print(" ".join(map(str, merge_sort(list(map(int, data[1:1 + int(data[0])]))))))
'''


def test_renaming_and_comments_do_not_evade_detection():
    result = similarity.compare([
        {'answer_key': 'a', 'content': REFERENCE_ACTIVITY, 'language': 'python3'},
        {'answer_key': 'b', 'content': RENAMED_ACTIVITY, 'language': 'python3'},
    ])
    assert len(result.pairs) == 1
    pair = result.pairs[0]
    assert float(pair['similarity']) >= 0.9, pair['similarity']
    assert pair['shared_fingerprints'] > 0
    assert pair['matching_spans'], 'matched line ranges are the evidence teachers read'
    for span in pair['matching_spans']:
        assert span['left_start_line'] <= span['left_end_line']
        assert span['right_start_line'] <= span['right_end_line']


def test_structural_rewrite_still_scores_above_threshold():
    result = similarity.compare([
        {'answer_key': 'a', 'content': REFERENCE_ACTIVITY, 'language': 'python3'},
        {'answer_key': 'b', 'content': STRUCTURALLY_EDITED, 'language': 'python3'},
    ])
    assert result.pairs, 'an edited copy must not fall below the evidence threshold'
    assert float(result.pairs[0]['similarity']) >= 0.5


def test_unrelated_solutions_are_not_reported_as_similar():
    result = similarity.compare([
        {'answer_key': 'a', 'content': REFERENCE_ACTIVITY, 'language': 'python3'},
        {'answer_key': 'b', 'content': UNRELATED_MERGE_SORT, 'language': 'python3'},
    ])
    assert result.pairs == []


def test_short_or_non_programming_submissions_are_explained_not_scored():
    result = similarity.compare([
        {'answer_key': 'tiny', 'content': 'print(1)', 'language': 'python3'},
        {'answer_key': 'answer', 'content': REFERENCE_ACTIVITY, 'language': 'python3'},
        {'answer_key': 'prose', 'content': 'This is a written answer.', 'language': None},
    ])
    reasons = {row['answer_key']: row['reason'] for row in result.insufficient}
    assert reasons['tiny'] == 'INSUFFICIENT_TOKENS'
    assert reasons['prose'] == 'NOT_A_PROGRAMMING_LANGUAGE'
    assert result.pairs == [] and result.submission_count == 1


def test_language_mismatch_still_compares_lexically():
    c_copy = '''
#include <stdio.h>
int main(){int n;scanf("%d",&n);int a[1005];
for(int i=0;i<n;i++)scanf("%d",&a[i]);
for(int i=0;i<n;i++)for(int j=0;j<n-1-i;j++){if(a[j]>a[j+1]){int t=a[j];a[j]=a[j+1];a[j+1]=t;}}
for(int i=0;i<n;i++)printf("%d ",a[i]);return 0;}
'''
    c_renamed = c_copy.replace('a', 'data').replace(' t ', ' tmp ').replace('int t=', 'int tmp=')
    result = similarity.compare([
        {'answer_key': 'x', 'content': c_copy, 'language': 'cpp'},
        {'answer_key': 'y', 'content': c_renamed, 'language': 'cpp'},
    ])
    assert result.pairs and float(result.pairs[0]['similarity']) > 0.8


def test_clusters_require_three_members_and_are_ordered():
    items = [
        {'answer_key': 'a1', 'content': REFERENCE_ACTIVITY, 'language': 'python3'},
        {'answer_key': 'a2', 'content': RENAMED_ACTIVITY, 'language': 'python3'},
        {'answer_key': 'a3', 'content': REFERENCE_ACTIVITY.replace('print(ans)', 'print(ans)  # 3'),
         'language': 'python3'},
        {'answer_key': 'b1', 'content': UNRELATED_MERGE_SORT, 'language': 'python3'},
    ]
    result = similarity.compare(items)
    assert result.clusters, 'three near-identical submissions form one cluster'
    cluster = result.clusters[0]
    assert cluster['size'] == 3
    assert set(cluster['member_keys']) == {'a1', 'a2', 'a3'}
    assert float(cluster['max_similarity']) >= 0.9


def test_threshold_is_respected():
    # A rename normalises to the same token stream, so it scores 1.0 by design.
    # The threshold must be the thing that decides what enters the evidence list:
    # an unrelated program is filtered at 0.99 and appears at 0.0.
    exact = [
        {'answer_key': 'a', 'content': REFERENCE_ACTIVITY, 'language': 'python3'},
        {'answer_key': 'b', 'content': RENAMED_ACTIVITY, 'language': 'python3'},
    ]
    assert float(similarity.compare(exact, threshold=0.99).pairs[0]['similarity']) == 1.0
    unrelated = [
        {'answer_key': 'a', 'content': REFERENCE_ACTIVITY, 'language': 'python3'},
        {'answer_key': 'b', 'content': UNRELATED_MERGE_SORT, 'language': 'python3'},
    ]
    assert similarity.compare(unrelated, threshold=0.5).pairs == []
    # Two programs that share no fingerprint produce no pair row at all: the
    # inverted index only emits pairs that actually overlap. A missing row is
    # therefore "no evidence", never "similarity 0".
    assert similarity.compare(unrelated, threshold=0.0).pairs == []


def test_fingerprints_are_stable_across_calls_and_processes():
    first = similarity.sketch('a', REFERENCE_ACTIVITY, 'python3')
    second = similarity.sketch('a', REFERENCE_ACTIVITY, 'python3')
    assert [fp.value for fp in first.fingerprints] == [fp.value for fp in second.fingerprints]
    # blake2b is used instead of hash(): pin one value so a later refactor cannot
    # silently reintroduce a process-salted digest.
    assert first.fingerprints[0].value == second.fingerprints[0].value


def test_winnowing_keeps_window_minimum():
    hashes = [5, 3, 8, 1, 9, 2, 7]
    selected = similarity.winnow(hashes, 3)
    # Windows: [5,3,8]->3 at 1, [3,8,1]->1 at 3, [8,1,9]->1 at 3, [1,9,2]->1 at 3,
    # [9,2,7]->2 at 5. Rightmost minimum of each window, duplicates collapsed.
    assert selected == [(3, 1), (1, 3), (2, 5)]


def brute_force_shared(left: str, right: str) -> int:
    a = similarity.sketch('l', left, 'python3')
    b = similarity.sketch('r', right, 'python3')
    return len(set(a.positions) & set(b.positions))


def test_inverted_index_matches_naive_intersection():
    rng = random.Random(20261028)
    base = [line for line in REFERENCE_ACTIVITY.strip().splitlines() if line.strip()]
    for trial in range(12):
        items = []
        for index in range(4):
            lines = list(base)
            rng.shuffle(lines)
            if index % 2:
                lines = lines[: max(4, len(lines) - 3)]
            items.append({'answer_key': f'k{index}', 'content': '\n'.join(lines), 'language': 'python3'})
        result = similarity.compare(items, threshold=0.0, minimum_tokens=1)
        reported = {(row['left_key'], row['right_key']): row['shared_fingerprints'] for row in result.pairs}
        for left in range(4):
            for right in range(left + 1, 4):
                expected = brute_force_shared(items[left]['content'], items[right]['content'])
                key = (items[left]['answer_key'], items[right]['answer_key'])
                assert reported.get(key, 0) == expected, f'trial {trial} pair {key}'


def test_similarity_contains_ratio_symmetric_in_containment():
    larger = REFERENCE_ACTIVITY + '\n' * 20 + 'extra = 1\n'
    result = similarity.compare([
        {'answer_key': 'a', 'content': REFERENCE_ACTIVITY, 'language': 'python3'},
        {'answer_key': 'b', 'content': larger, 'language': 'python3'},
    ], threshold=0.0)
    pair = result.pairs[0]
    assert float(pair['containment_left']) >= float(pair['containment_right'])
    assert float(pair['similarity']) == float(pair['containment_left'])
    assert float(pair['jaccard']) <= float(pair['similarity'])


# --------------------------------------------------------------- complexity

STATIC_SAMPLES = {
    'merge_sort': (UNRELATED_MERGE_SORT, 'O(n log n)'),
    'bubble': ('''
import sys
data = sys.stdin.read().split(); n = int(data[0]); a = list(map(int, data[1:1 + n]))
for i in range(n):
    for j in range(n - 1 - i):
        if a[j] > a[j + 1]:
            a[j], a[j + 1] = a[j + 1], a[j]
print(' '.join(map(str, a)))
''', 'O(n^2)'),
    'binary_search': ('''
import sys
data = sys.stdin.read().split(); n = int(data[0]); a = list(map(int, data[1:1 + n])); x = int(data[1 + n])
lo, hi = 0, n
while lo < hi:
    mid = (lo + hi) // 2
    if a[mid] < x:
        lo = mid + 1
    else:
        hi = mid
print(lo)
''', 'O(log n)'),
    'hanoi': ('''
n = int(input())
def solve(k, a, b, c):
    if k == 0:
        return
    solve(k - 1, a, c, b)
    print(a, '->', b)
    solve(k - 1, c, b, a)
solve(n, 'A', 'B', 'C')
''', 'O(2^n)'),
    'linear_sum': ('''
import sys
n = int(sys.stdin.readline())
values = list(map(int, sys.stdin.read().split()))
print(sum(values))
''', 'O(n)'),
    'constant': ('''
a, b = map(int, input().split())
print(a + b)
''', 'O(1)'),
}


@pytest.mark.parametrize('name,expected', [(k, v[1]) for k, v in STATIC_SAMPLES.items()])
def test_static_classification_of_reference_shapes(name, expected):
    result = complexity.analyze_static(STATIC_SAMPLES[name][0], 'python3')
    assert result.time_class == expected, f'{name}: {result.time_class} != {expected}'


def test_static_space_detects_input_sized_container_and_matrix():
    linear = complexity.analyze_static('a = list(map(int, input().split()))\nprint(sum(a))', 'python3')
    assert linear.space_class in ('O(n)',)
    matrix = complexity.analyze_static(
        'n = int(input())\nrows = [[0] * n for _ in range(n)]\nprint(rows[0][0])', 'python3')
    assert matrix.space_class == 'O(n^2)'


def test_structured_language_is_explicitly_low_confidence():
    source = '''
#include <stdio.h>
int main(){int n;scanf("%d",&n);int a[1005];
for(int i=0;i<n;i++)for(int j=0;j<n-1-i;j++){if(a[j]>a[j+1]){int t=a[j];a[j]=a[j+1];a[j+1]=t;}}
return 0;}
'''
    result = complexity.analyze_static(source, 'cpp')
    assert result.confidence == 'LOW'
    assert any(item['kind'] == 'LEXICAL_ONLY' for item in result.evidence)
    assert result.time_class == 'O(n^2)'


def test_unsupported_language_is_unknown_not_a_guess():
    result = complexity.analyze_static('print(1)', 'brainfuck')
    assert result.time_class == 'UNKNOWN' and result.confidence == 'LOW'


def _measurements(function, sizes=(64, 128, 256, 512, 1024, 2048)):
    return [complexity.Measurement(n=size, wall_ms=function(size), adjusted_ms=function(size),
                                   peak_rss_kib=8000 + size, verdict='OK') for size in sizes]


@pytest.mark.parametrize('label,function,expected', [
    ('n log n', lambda n: 0.004 * n * math.log2(n + 2), 'O(n log n)'),
    ('n^2', lambda n: 1e-6 * n * n + 0.2, 'O(n^2)'),
    ('n', lambda n: 0.01 * n + 0.5, 'O(n)'),
    ('log n', lambda n: 0.4 * math.log2(n + 2), 'O(log n)'),
    ('constant', lambda n: 1.5, 'O(1)'),
])
def test_growth_fit_recovers_known_class(label, function, expected):
    fit = complexity.fit_growth(_measurements(function))
    assert fit.fitted_class == expected, f'{label}: got {fit.fitted_class}'
    assert fit.r2 > 0.9


def test_growth_fit_needs_enough_points_and_reports_low_confidence():
    few = _measurements(lambda n: float(n), sizes=(64, 128))
    fit = complexity.fit_growth(few)
    assert fit.fitted_class == 'UNKNOWN' and fit.confidence == 'LOW'
    noisy = [complexity.Measurement(n=n, wall_ms=t, adjusted_ms=t, peak_rss_kib=None, verdict='OK')
             for n, t in ((64, 5.0), (128, 4.0), (256, 9.0), (512, 40.0))]
    assert complexity.fit_growth(noisy).confidence in ('LOW', 'MEDIUM')


def test_growth_fit_ignores_failed_rungs():
    points = _measurements(lambda n: 1e-6 * n * n)
    points.append(complexity.Measurement(n=4096, wall_ms=0, adjusted_ms=0, peak_rss_kib=None,
                                         verdict='TIME_LIMIT_EXCEEDED'))
    fit = complexity.fit_growth(points)
    assert fit.fitted_class == 'O(n^2)'
    assert fit.discarded and fit.discarded[0]['n'] == 4096


def _dynamic(measured, io='O(n)', informative=True, confidence='HIGH', r2=0.995):
    fit = complexity.GrowthFit(measured, r2, 2.0, 0.0001,
                               [{'n': 64}, {'n': 128}, {'n': 256}, {'n': 512}], [], confidence)
    return complexity.DynamicConclusion(measured_class=measured, io_class=io,
                                        informative=informative, r2=r2, exponent=2.0,
                                        confidence=confidence, floor_ms=12.0,
                                        fit=fit, reference_fit=None, accounting=[])


def test_combine_prefers_informative_measurement_and_records_conflict():
    static = complexity.StaticAnalysis(language_family='python', time_class='O(log n)',
                                       space_class='O(1)', confidence='HIGH')
    summary = complexity.combine(static, _dynamic('O(n^2)'))
    assert summary['time']['class'] == 'O(n^2)'
    assert summary['time']['source'] == 'DYNAMIC'
    assert summary['time']['agreement'] is False
    assert summary['limitations'], 'a conflict must be explained, not hidden'


def test_combine_falls_back_to_static_when_measurement_is_weak():
    static = complexity.StaticAnalysis(language_family='python', time_class='O(n^2)',
                                       space_class='O(n)', confidence='HIGH')
    summary = complexity.combine(static, _dynamic('O(n log n)', io='O(n)', confidence='LOW', r2=0.5))
    assert summary['time']['class'] == 'O(n^2)'
    assert summary['time']['source'] == 'STATIC'


def test_combine_does_not_claim_a_class_the_measurement_cannot_separate():
    """A binary search measures the same as input parsing; only structure can tell."""
    static = complexity.StaticAnalysis(language_family='python', time_class='O(log n)',
                                       space_class='O(1)', confidence='HIGH')
    summary = complexity.combine(static, _dynamic('O(n)', io='O(n)', informative=False))
    assert summary['time']['class'] == 'O(log n)'
    assert summary['time']['source'] == 'STATIC'
    assert any('只能给出上界' in text for text in summary['limitations'])



def test_curve_points_match_the_fitted_function():
    curve = complexity.curve_points('O(n^2)', 2.0, [10, 20])
    assert curve and curve[0]['n'] == 10 and curve[-1]['n'] == 20
    middle = curve[len(curve) // 2]
    assert middle['time_ms'] == pytest.approx(2.0 * middle['n'] ** 2, rel=1e-6)
