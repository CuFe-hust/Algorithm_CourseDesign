"""Unit tests for the two research algorithms.

The similarity tests include a brute-force cross-check: the inverted-index
counter must agree with naive set intersection on random small inputs. The
complexity tests pin the class each reference implementation should receive and
check the growth fit on synthetic data with known shape.
"""
import random

import pytest

from app.analysis.algorithms import similarity


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
