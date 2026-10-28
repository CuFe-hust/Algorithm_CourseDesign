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


def test_cluster_reports_how_many_pairs_actually_qualify():
    """A cluster is a connected component, not a clique, and must say so.

    Review measured a real 8-member cluster where only 8 of the 28 member pairs
    reached the threshold; showing only "8 份 · 最高 0.67" invites reading a chain
    as a group of mutual copies.
    """
    head = "import sys\ndata = sys.stdin.read().split()\nn = int(data[0])\nvals = [int(x) for x in data[1:1+n]]\n"
    block_one = """total = 0
for i in range(n):
    for j in range(i + 1, n):
        if vals[i] > vals[j]:
            total += vals[i] - vals[j]
        else:
            total += vals[j] - vals[i]
print(total % 9973)
"""
    block_two = """best = 0
current = 0
for x in vals:
    if x % 3 == 0:
        current = 0
    else:
        current = current + x
        if current > best:
            best = current
print(best % 997)
"""
    first = head + block_one
    middle = head + block_one + block_two
    last = head + block_two
    result = similarity.compare([
        dict(answer_key='a', content=first, language='python3'),
        dict(answer_key='b', content=middle, language='python3'),
        dict(answer_key='c', content=last, language='python3')])
    assert len(result.clusters) == 1
    cluster = result.clusters[0]
    assert cluster['size'] == 3
    # a~b and b~c qualify; a~c shares only the boilerplate and does not.
    assert cluster['qualifying_pairs'] == 2
    assert cluster['total_pairs'] == 3
    assert float(cluster['min_similarity']) >= 0.5


def test_pairs_carry_the_token_count_of_each_side():
    """Evidence strength depends on program length; the reader needs the counts.

    Independent implementations of one standard algorithm converge to 0.54-1.00
    below ~120 tokens when the class shares an I/O idiom, so a high score between
    two short submissions must be readable as weak evidence.
    """
    head = "import sys\ndata = sys.stdin.read().split()\nn = int(data[0])\nvals = [int(x) for x in data[1:1+n]]\n"
    tail = "print(sum(vals) % 7)\n"
    short = head + tail
    longer = head + "acc = 0\nfor x in vals:\n    acc += x * 2\n" + tail
    result = similarity.compare([
        dict(answer_key='a', content=short, language='python3'),
        dict(answer_key='b', content=longer, language='python3')], threshold=0.0)
    pair = result.pairs[0]
    assert pair['left_tokens'] == similarity.tokenize_source(short, 'python3').__len__()
    assert pair['right_tokens'] == len(similarity.tokenize_source(longer, 'python3'))


def test_merge_spans_rejects_a_backwards_jump_on_either_side():
    """Anchors are ordered by the left position only, so the right side needs a
    lower bound: otherwise a block moved from the bottom to the top merges into one
    span whose reported range does not cover the tokens it claims."""
    k = 12
    forward = [
        similarity._Anchor(0, 0, 1, 1, 1, 1),
        similarity._Anchor(k, k, 2, 2, 2, 2),
    ]
    assert len(similarity._merge_spans(forward, k)) == 1

    backwards = [
        similarity._Anchor(0, 200, 1, 1, 20, 20),
        similarity._Anchor(k, 0, 2, 2, 1, 1),
    ]
    spans = similarity._merge_spans(backwards, k)
    assert len(spans) == 2, 'a backwards right-side jump must break the span'


def test_spans_do_not_merge_a_backwards_jump():
    """Moved code must break a span, not produce one range that covers nothing.

    Without a lower bound on the right side, a block cut from the bottom and
    pasted at the top merged matches whose right positions jump backwards, and the
    reported line range did not cover the tokens claimed.
    """
    body = [f"a[{index}] = a[{index}] + {index}" for index in range(10)]
    original = ("n = int(input())\na = list(map(int, input().split()))\n"
                + "\n".join(body) + "\nprint(a)\n")
    moved = ("n = int(input())\na = list(map(int, input().split()))\n"
             + "\n".join(body[6:] + body[:6]) + "\nprint(a)\n")
    result = similarity.compare([
        dict(answer_key='a', content=original, language='python3'),
        dict(answer_key='b', content=moved, language='python3')])
    assert result.pairs, 'a moved block still shares most of its tokens'
    for span in result.pairs[0]['matching_spans']:
        assert span['left_end_line'] >= span['left_start_line']
        assert span['right_end_line'] >= span['right_start_line']


def test_compare_states_when_the_evidence_list_was_truncated():
    """A cut evidence list must be labelled, and the cluster list stays complete.

    The teacher page reads this flag; without it a 500-row list looks like the
    whole result. Clusters are built from the full threshold graph, so even a
    truncated result still names every similar group.
    """
    source = """n = int(input())
items = [tuple(map(int, input().split())) for _ in range(n)]
items.sort()
print(len(items))
"""
    copies = [dict(answer_key=f'a{index}', content=source, language='python3') for index in range(30)]
    result = similarity.compare(copies, max_pairs=10)
    assert result.pairs_truncated is True
    assert len(result.pairs) == 10
    assert [cluster['size'] for cluster in result.clusters] == [30]

    roomy = similarity.compare(copies, max_pairs=500)
    assert roomy.pairs_truncated is False
    assert len(roomy.pairs) == 30 * 29 // 2


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


def _ideal_ladder(time_class: str, sizes=(256, 323, 406, 512, 645, 813, 1024),
                  amplitude=24.0, start_up=12.0) -> list:
    """Noiseless affine data for one class, the model the fitter is asked to invert."""
    function = complexity.GROWTH_FUNCTIONS[time_class]
    base = function(sizes[0])
    points = []
    for n in sizes:
        wall = start_up + amplitude * function(n) / base
        points.append(complexity.Measurement(n=n, wall_ms=wall, adjusted_ms=wall,
                                             peak_rss_kib=None, verdict='OK'))
    return points


@pytest.mark.parametrize('time_class', ['O(1)', 'O(log n)', 'O(n)', 'O(n log n)', 'O(n^2)', 'O(n^3)'])
def test_fit_recovers_every_class_from_a_noiseless_ladder(time_class):
    """The fitter must invert its own model.

    This is the regression that motivated the tie-break change: with the old
    ``R^2 + 0.005`` rule, ideal ``n log n`` data was reported as ``O(n)`` on
    every run, because on a doubling ladder the two bases are nearly collinear
    and their R^2 differ by ~0.0006.
    """
    fit = complexity.fit_growth(_ideal_ladder(time_class), floor_ms=12.0)
    assert fit.fitted_class == time_class, (time_class, fit.fitted_class, fit.r2)
    assert fit.r2 > 0.999


def test_fit_keeps_the_log_factor_when_the_residual_really_drops():
    points = _ideal_ladder('O(n log n)')
    fit = complexity.fit_growth(points, floor_ms=12.0)
    assert fit.fitted_class == 'O(n log n)'
    assert fit.coefficient > 0


def test_choose_class_keeps_a_log_factor_only_when_the_residual_really_drops():
    """The tie-break rule, tested on residuals directly.

    End-to-end noisy data cannot state this cleanly: on a wide ladder a log factor
    also absorbs part of the noise, so "spurious log factor" is not a reliably
    testable claim. What the rule does guarantee is the decision procedure, and
    that is what this asserts.
    """
    total = 1000.0
    # Same R^2 window; the higher class cuts the residual by 1.43x, above the
    # 1.33 fold for a seven-rung ladder.
    kept = complexity._choose_class(
        [('O(n)', 1 - 1.0 / total, 1.0, 0.0), ('O(n log n)', 1 - 0.7 / total, 1.0, 0.0)],
        total, 7)
    assert kept[0] == 'O(n log n)'
    # The higher class only cuts the residual by 1.18x: not worth the parameter.
    dropped = complexity._choose_class(
        [('O(n)', 1 - 1.0 / total, 1.0, 0.0), ('O(n log n)', 1 - 0.85 / total, 1.0, 0.0)],
        total, 7)
    assert dropped[0] == 'O(n)'


def test_choose_class_never_skips_an_adjacent_rank():
    """Stepping down is one rank at a time, not "the lowest rank that passes".

    Review found the single-scan form could jump from O(n^2) straight to O(1) when
    several coarse classes sat inside the same R^2 window. A middle rank that fails
    the fold must therefore stop the walk, not be skipped over.
    """
    total = 1000.0
    # O(n) fails the fold (residual 1.4x) but O(1) would pass (residual 1.2x).
    # The walk must stop at O(n^2), not jump over O(n) to O(1).
    kept = complexity._choose_class(
        [('O(1)', 1 - 1.2 / total, 1.0, 0.0),
         ('O(n)', 1 - 1.4 / total, 1.0, 0.0),
         ('O(n^2)', 1 - 1.0 / total, 1.0, 0.0)],
        total, 7)
    assert kept[0] == 'O(n^2)', kept[0]


def test_choose_class_walks_down_two_adjacent_ranks_when_both_pass():
    total = 1000.0
    walked = complexity._choose_class(
        [('O(1)', 1 - 1.2 / total, 1.0, 0.0),
         ('O(n)', 1 - 1.25 / total, 1.0, 0.0),
         ('O(n^2)', 1 - 1.0 / total, 1.0, 0.0)],
        total, 7)
    # Both steps are within the 1.33 fold, so both are taken.
    assert walked[0] == 'O(1)', walked[0]


def test_sse_improvement_fold_shrinks_as_the_ladder_grows():
    assert complexity.sse_improvement_fold(7) > complexity.sse_improvement_fold(13)
    assert 1.1 < complexity.sse_improvement_fold(13) < complexity.sse_improvement_fold(7) < 1.5


def _dynamic_conclusion(measured: str, confidence: str = 'HIGH'):
    fit = complexity.GrowthFit(measured, 0.997, 1.1, 0.0001,
                               [{'n': 256}, {'n': 512}, {'n': 1024}, {'n': 2048}], [], confidence)
    return complexity.DynamicConclusion(measured_class=measured, io_class='UNKNOWN',
                                        informative=True, r2=0.997, exponent=1.1,
                                        confidence=confidence, floor_ms=12.0, fit=fit,
                                        reference_fit=None, accounting=[])


def _measured(points: list[tuple[int, float]], verdict: str = 'OK') -> list:
    return [complexity.Measurement(n=n, wall_ms=ms, adjusted_ms=ms,
                                   peak_rss_kib=None, verdict=verdict)
            for n, ms in points]


def test_informative_requires_clearly_outrunning_the_reader():
    """The old class-vs-class check never fired; the ratio check must.

    A reader is a constant-cost program, so its own growth fit comes back LOW and
    io_class stayed UNKNOWN on every recorded run. Judging per rung instead: no
    reference at all means unverified, ratios below the threshold on every rung
    means input parsing dominates, and three clear rungs means real evidence.
    """
    ladder = [(256, 12.0), (512, 14.0), (1024, 20.0), (2048, 32.0), (4096, 60.0)]

    # No baseline (C/C++/Java): unverified, not refuted.
    unverified = complexity.classify_growth(_measured(ladder))
    assert unverified.informative is True

    # Reader keeps pace everywhere: measurement is an upper bound only.
    reader_paced = complexity.classify_growth(
        _measured(ladder), {n: ms * 0.9 for n, ms in ladder})
    assert reader_paced.informative is False

    # The submission clearly outruns the reader on most rungs.
    real_work = complexity.classify_growth(
        _measured(ladder), {n: ms / 2 for n, ms in ladder})
    assert real_work.informative is True

    # Only two rungs stand out: not enough evidence of algorithm work.
    sparse = {256: 13.0, 512: 15.5, 1024: 22.0, 2048: 16.0, 4096: 61.0}
    barely = complexity.classify_growth(_measured(ladder), sparse)
    assert barely.informative is False


@pytest.mark.parametrize('static_class,measured', [
    ('O(n log n)', 'O(n)'),
    ('O(n)', 'O(n log n)'),
    ('O(n^2)', 'O(n^2 log n)'),
    ('O(log n)', 'O(1)'),
])
def test_combine_lets_structure_decide_a_log_factor(static_class, measured):
    """A clock cannot separate classes that differ by one log factor."""
    static = complexity.StaticAnalysis(language_family='python', time_class=static_class,
                                       space_class='O(1)', confidence='HIGH')
    summary = complexity.combine(static, _dynamic_conclusion(measured))
    assert summary['time']['class'] == static_class
    assert summary['time']['source'] == 'STATIC'
    assert summary['time']['confidence'] == 'MEDIUM'
    assert summary['time']['agreement'] is False
    assert any('log 因子' in text for text in summary['limitations'])


def test_combine_does_not_let_a_lexical_analysis_rule_a_log_factor():
    """C/C++/Java static analysis is lexical and LOW-confidence; it must not
    override a confident measurement on the log-factor pair it is most likely
    to get wrong."""
    static = complexity.StaticAnalysis(language_family='c-like', time_class='O(n)',
                                       space_class='O(1)', confidence='LOW')
    summary = complexity.combine(static, _dynamic_conclusion('O(n log n)'))
    assert summary['time']['class'] == 'O(n log n)'
    assert summary['time']['source'] == 'DYNAMIC'
    assert any('词法分析' in text for text in summary['limitations'])


def test_combine_still_prefers_a_clearly_higher_measurement():
    """The log-factor rule must not turn into "static always wins"."""
    static = complexity.StaticAnalysis(language_family='python', time_class='O(n)',
                                       space_class='O(1)', confidence='HIGH')
    summary = complexity.combine(static, _dynamic_conclusion('O(n^2)'))
    assert summary['time']['class'] == 'O(n^2)'
    assert summary['time']['source'] == 'DYNAMIC'


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


def test_static_ignores_a_loop_with_a_literal_bound():
    """``for _ in range(10)`` is constant work; it must not become a factor of n."""
    code = """n = int(input())
total = 0
for _ in range(10):
    total += 1
for value in range(n):
    total += value
print(total)
"""
    analysis = complexity.analyze_static(code, 'python3')
    assert analysis.time_class == 'O(n)'
    assert analysis.loop_depth == 1


def test_a_literal_bound_loop_never_becomes_a_factor_of_n():
    """Push and pop must agree on the constant weight.

    A literal-bound loop contributes nothing, so leaving it must remove nothing.
    The first version only changed ``push``: a constant loop placed before a real
    inner loop silently deleted the enclosing factor of n.
    """
    inner_first = """n = int(input())
a = list(map(int, input().split()))
total = 0
for i in range(n):
    for bit in range(8):
        total += (a[i] >> bit) & 1
    for j in range(n):
        if a[j] > a[i]:
            total += 1
print(total)
"""
    inner_second = """n = int(input())
a = list(map(int, input().split()))
total = 0
for i in range(n):
    for j in range(n):
        if a[j] > a[i]:
            total += 1
    for bit in range(8):
        total += (a[i] >> bit) & 1
print(total)
"""
    only_constant = """n = int(input())
a = list(map(int, input().split()))
total = 0
for i in range(n):
    for bit in range(8):
        total += (a[i] >> bit) & 1
print(total)
"""
    for source, expected in ((inner_first, 'O(n^2)'), (inner_second, 'O(n^2)'),
                             (only_constant, 'O(n)')):
        assert complexity.analyze_static(source, 'python3').time_class == expected


def test_a_literal_bound_comprehension_is_not_a_factor_of_n():
    """The same rule has to hold for comprehensions, not just ``for`` statements."""
    fixed_board = """board = [list("0" * 9) for _ in range(9)]
print(board)
"""
    assert complexity.analyze_static(fixed_board, 'python3').time_class == 'O(1)'

    input_sized = """n = int(input())
values = [int(token) for token in range(n)]
print(len(values))
"""
    assert complexity.analyze_static(input_sized, 'python3').time_class == 'O(n)'


def test_static_counts_a_while_loop_as_input_dependent():
    """A ``while`` bound is a variable, so it stays conservative.

    ``while t < 9`` may well be constant, but nothing in the syntax proves it: the
    same shape is ``while lo < n`` in every binary search. Counting it as a factor
    of n keeps the estimator from under-reporting a real loop.
    """
    source = """n = int(input())
total = 0
while total < 9:
    total += n
print(total)
"""
    analysis = complexity.analyze_static(source, 'python3')
    assert analysis.loop_depth == 1


def test_static_counts_a_loop_whose_bound_is_the_input():
    code = """n = int(input())
total = 0
for i in range(n):
    for j in range(n):
        total += i * j
print(total)
"""
    analysis = complexity.analyze_static(code, 'python3')
    assert analysis.time_class == 'O(n^2)'
    assert analysis.loop_depth == 2


def test_static_treats_an_input_sized_constant_loop_as_logarithmic():
    """60000 fixed iterations of a halving search is O(log n), not O(n log n)."""
    code = """import sys
n = int(sys.stdin.buffer.read().split()[0])
total = 0
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
"""
    analysis = complexity.analyze_static(code, 'python3')
    assert analysis.time_class == 'O(log n)'


def test_fit_needs_five_rungs_before_it_claims_medium_confidence():
    """Four points cannot pin a curve; the experiment saw O(n^2) land on O(n log n)."""
    four = _ideal_ladder('O(n^2)', sizes=(256, 512, 1024, 2048))
    five = _ideal_ladder('O(n^2)', sizes=(256, 512, 1024, 2048, 4096))
    assert complexity.fit_growth(four, floor_ms=12.0).confidence == 'LOW'
    assert complexity.fit_growth(five, floor_ms=12.0).confidence in ('MEDIUM', 'HIGH')


def test_upper_bound_wording_does_not_claim_an_unknown_reader_class():
    """When ratios are low but the reader fit never produced a class, the report
    must not say "same class as the reader (UNKNOWN)"."""
    static = complexity.StaticAnalysis(language_family='python', time_class='O(n^2)',
                                       space_class='O(1)', confidence='HIGH')
    fit = complexity.GrowthFit('O(n log n)', 0.95, 1.1, 0.0001,
                               [{'n': 256}], [], 'MEDIUM')
    dynamic = complexity.DynamicConclusion(
        measured_class='O(n log n)', io_class='UNKNOWN', informative=False, r2=0.95,
        exponent=1.1, confidence='MEDIUM', floor_ms=12.0, fit=fit,
        reference_fit=None, accounting=[])
    summary = complexity.combine(static, dynamic)
    text = ' '.join(summary['limitations'])
    assert summary['time']['class'] == 'O(n^2)'
    assert '1.5 倍' in text
    assert 'UNKNOWN' not in text


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
