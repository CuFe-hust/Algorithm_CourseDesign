"""C/C++ trace collection end to end: compile, count, fit.

These tests run the real toolchain (coverage build, ``gcov``, and the memory
counter) on small but genuine programs. They are skipped on a node without
``g++``/``gcc``/``gcov`` instead of pretending the adapter works.
"""
import shutil

import pytest

from app.analysis.trace import collect as trace_collect
from app.analysis.trace import infer as trace_infer

pytestmark = pytest.mark.skipif(
    not all(shutil.which(tool) for tool in ('g++', 'gcc', 'gcov')),
    reason='本机没有 g++/gcc/gcov，无法运行 C/C++ 执行轨迹测试')

MERGE_SORT = r'''
#include <iostream>
#include <vector>

static void merge_sort(std::vector<int>& a, int lo, int hi, std::vector<int>& tmp) {
    if (hi - lo < 2) return;
    int mid = (lo + hi) / 2;
    merge_sort(a, lo, mid, tmp);
    merge_sort(a, mid, hi, tmp);
    int i = lo, j = mid, k = lo;
    while (i < mid && j < hi) tmp[k++] = a[i] <= a[j] ? a[i++] : a[j++];
    while (i < mid) tmp[k++] = a[i++];
    while (j < hi) tmp[k++] = a[j++];
    for (int p = lo; p < hi; ++p) a[p] = tmp[p];
}

int main() {
    std::ios::sync_with_stdio(false);
    std::cin.tie(nullptr);
    int n;
    if (!(std::cin >> n)) return 0;
    std::vector<int> a(n);
    for (int i = 0; i < n; ++i) std::cin >> a[i];
    std::vector<int> tmp(n);
    merge_sort(a, 0, n, tmp);
    long long checksum = 0;
    for (int i = 0; i < n; ++i) checksum = (checksum * 131 + a[i]) % 1000000007;
    std::cout << checksum << "\n";
    return 0;
}
'''

BUBBLE_SORT = r'''
#include <iostream>
#include <vector>

int main() {
    std::ios::sync_with_stdio(false);
    std::cin.tie(nullptr);
    int n;
    if (!(std::cin >> n)) return 0;
    std::vector<int> a(n);
    for (int i = 0; i < n; ++i) std::cin >> a[i];
    for (int i = 0; i < n; ++i)
        for (int j = 0; j + 1 < n - i; ++j)
            if (a[j] > a[j + 1]) std::swap(a[j], a[j + 1]);
    std::cout << a[0] << "\n";
    return 0;
}
'''

LINEAR_SUM = r'''
#include <stdio.h>

int main(void) {
    int n;
    if (scanf("%d", &n) != 1) return 0;
    long long total = 0;
    for (int i = 0; i < n; i++) {
        int value;
        if (scanf("%d", &value) != 1) return 0;
        total += value;
    }
    printf("%lld\n", total);
    return 0;
}
'''

BROKEN = r'''
int main() {
    return this_identifier_does_not_exist;
}
'''


def _analyse(source: str, language: str, family: str, spec: dict, seed: int = 17):
    ladder = trace_collect.collect(source, language, family, spec, seed=seed)
    conclusion = trace_infer.infer(ladder, language_label=trace_collect.language_label(language))
    return ladder, conclusion


def test_cpp_merge_sort_is_n_log_n():
    ladder, conclusion = _analyse(MERGE_SORT, 'cpp', 'INT_ARRAY', {'max_n': 2048})
    assert ladder.language == 'cpp'
    assert len(ladder.ok_points) >= 5
    assert conclusion.time.time_class == 'O(n log n)'
    assert conclusion.time.confidence in ('MEDIUM', 'HIGH')
    # Counted lines are exact, so a deterministic program repeats exactly.
    assert ladder.deterministic is True
    assert ladder.points[-1].peak_bytes


def test_cpp_bubble_sort_is_quadratic():
    ladder, conclusion = _analyse(BUBBLE_SORT, 'cpp', 'INT_ARRAY', {'max_n': 1024})
    assert ladder.language == 'cpp'
    assert len(ladder.ok_points) >= 5
    assert conclusion.time.time_class == 'O(n^2)'
    assert conclusion.time.confidence in ('MEDIUM', 'HIGH')


def test_c_linear_sum_is_linear():
    ladder, conclusion = _analyse(LINEAR_SUM, 'c', 'INT_ARRAY', {'max_n': 2048})
    assert ladder.language == 'c'
    assert len(ladder.ok_points) >= 5
    assert conclusion.time.time_class == 'O(n)'
    assert conclusion.time.confidence in ('MEDIUM', 'HIGH')
    # C has no allocation hook, so no peak is claimed.
    assert all(point.peak_bytes is None for point in ladder.points)


def test_compilation_error_is_reported_as_one_point():
    ladder, _ = _analyse(BROKEN, 'cpp', 'INT_ARRAY', {'max_n': 256})
    assert ladder.stop_reason == 'COMPILATION_ERROR'
    assert len(ladder.points) == 1
    point = ladder.points[0]
    assert point.verdict == 'COMPILATION_ERROR'
    assert point.detail and len(point.detail) <= 400
    assert point.ok is False


STD_SORT = r'''
#include <algorithm>
#include <iostream>
#include <vector>

int main() {
    std::ios::sync_with_stdio(false);
    std::cin.tie(nullptr);
    int n;
    if (!(std::cin >> n)) return 0;
    std::vector<int> a(n);
    for (int i = 0; i < n; ++i) std::cin >> a[i];
    std::sort(a.begin(), a.end());
    std::cout << a[0] << "\n";
    return 0;
}
'''

SMALL_SORT_IN_LOOP = r'''
#include <algorithm>
#include <iostream>
#include <vector>

int main() {
    std::ios::sync_with_stdio(false);
    std::cin.tie(nullptr);
    int n;
    if (!(std::cin >> n)) return 0;
    std::vector<int> a(n);
    for (int i = 0; i < n; ++i) std::cin >> a[i];
    long long total = 0;
    for (int i = 0; i < n; ++i) {
        std::vector<int> bucket{a[i], a[(i + 1) % n], a[(i + 2) % n], a[(i + 3) % n]};
        std::sort(bucket.begin(), bucket.end());
        total += bucket[0];
    }
    std::cout << total << "\n";
    return 0;
}
'''


def test_std_sort_is_not_reported_as_linear():
    """The libc++ sort instantiation for int lives in the precompiled library, so
    its internal work is invisible to gcov. Without the library cost table this
    program is reported as O(n); it must be O(n log n)."""
    ladder = trace_collect.collect(STD_SORT, 'cpp', 'INT_ARRAY', {'max_n': 2048}, seed=3)
    assert len(ladder.ok_points) >= 4
    conclusion = trace_infer.infer(ladder, language_label='C++17')
    assert conclusion.time.time_class == 'O(n log n)', (
        conclusion.time.time_class,
        [(point.n, point.work, point.library_work) for point in ladder.points])
    assert any('标准库' in note for note in ladder.notes)
    assert any(point.library_work > 0 for point in ladder.ok_points)


def test_sorting_small_arrays_in_a_loop_stays_linear():
    """A loop that sorts a four-element array n times is O(n). Pricing each of
    those calls at n log n would wrongly turn it into O(n^2 log n)."""
    ladder = trace_collect.collect(SMALL_SORT_IN_LOOP, 'cpp', 'INT_ARRAY', {'max_n': 1024},
                                   seed=3)
    assert len(ladder.ok_points) >= 4
    conclusion = trace_infer.infer(ladder, language_label='C++17')
    assert conclusion.time.time_class in ('O(n)', 'O(n log n)'), conclusion.time.time_class
