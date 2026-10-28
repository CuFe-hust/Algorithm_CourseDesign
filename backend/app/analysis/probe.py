"""Deterministic input generation and ladder planning.

The complexity analysis no longer times the submission, so this module only
builds *valid, scalable inputs*. Executing them and counting work is the job of
:mod:`app.analysis.trace`; the wall-clock ladder, the pure-reader baseline and
the escalation rules that used to live here were removed with the timing route.

The generator is deterministic: the same family, size and seed always produce
byte-identical input, so a stored report can be reproduced later. Every family
must produce input that fits the problem's declared format, and seeding
acceptance-tests that against the bank's own reference solution: an invalid
input would only measure the program's error path.
"""
from __future__ import annotations

import random
from dataclasses import dataclass

FAMILIES = ('SINGLE_INT', 'TWO_INTS', 'THREE_INTS', 'INT_ARRAY', 'INT_ARRAY_ROWS',
            'INT_ARRAY_QUERIES', 'INT_ARRAY_WITH_K', 'SORTED_ARRAY_QUERIES',
            'INT_ARRAY_OPERATIONS', 'TWO_INT_ARRAYS', 'INT_ARRAY_ROWS_TWO_HEADER',
            'GRAPH_EDGES', 'GRAPH_TREE_QUERIES', 'GRAPH_EDGE_QUERIES', 'GRAPH_COLORING',
            'TWO_STRINGS', 'BIG_TWO_STRINGS', 'STRING_LIST', 'ONE_STRING',
            'STRING_RANGE_QUERIES', 'POSTFIX_EXPRESSION', 'STACK_OPERATIONS',
            'GRID', 'GRID_WITH_WORD', 'MATRIX',
            'TRIANGLE_ROWS', 'KNAPSACK', 'FIXED', 'EXISTING_CASES')

# Sizes are small on purpose. Counts are exact, so a handful of doublings is
# enough to separate even n from n log n; large inputs would only cost tracing
# time. The adapter stops early when the work budget is reached.
DEFAULT_SIZES = (32, 64, 128, 256, 512, 1024, 2048, 4096, 8192, 16384)
SMALL_MAX_N = 96
MAX_INPUT_BYTES = 12 * 1024 * 1024

# Families whose ``n`` is a *number in the input* rather than the amount of data.
# A larger n costs no extra input bytes, so the ladder can climb much higher and
# separate logarithmic work (extended Euclid, fast power) from constant work.
VALUE_FAMILIES = frozenset({'SINGLE_INT', 'TWO_INTS', 'THREE_INTS'})
VALUE_SIZES = (64, 256, 1024, 4096, 16384, 65536, 262144, 1048576)


class ProfileError(ValueError):
    """The stored profile cannot produce a valid input for this problem."""


@dataclass
class Rung:
    n: int
    input_text: str


def _ints(rng: random.Random, count: int, low: int, high: int) -> list[int]:
    return [rng.randint(low, high) for _ in range(count)]


def _permutation(rng: random.Random, n: int) -> list[int]:
    values = list(range(1, n + 1))
    rng.shuffle(values)
    return values


def _string(rng: random.Random, n: int, alphabet: str) -> str:
    return ''.join(rng.choice(alphabet) for _ in range(max(1, n)))


def _value_bound(spec: dict, size: int) -> int:
    """Upper bound for array elements: the problem's bound, else the size."""
    return max(2, min(int(spec.get('max_value', 0) or 0) or size, max(2, size)))


def generate(family: str, n: int, seed: int, spec: dict | None = None) -> str:
    """Return one input text for the given family and size ``n``."""
    spec = spec or {}
    rng = random.Random(f'{seed}:{family}:{n}')
    n = max(1, int(n))
    if family == 'SINGLE_INT':
        low = int(spec.get('min', 1))
        high = int(spec.get('max', 10 ** 9))
        return f'{max(low, min(high, n))}\n'
    if family == 'TWO_INTS':
        # Two integers that follow n. ``scale_*`` and ``offset_*`` shape the
        # pair: a base-conversion problem keeps the second value at the base,
        # a Euclid-style problem keeps the two values on the same scale.
        first = max(1, min(int(spec.get('max_a', 10 ** 9)),
                           int(n * float(spec.get('scale_a', 1))) + int(spec.get('offset_a', 0))))
        second = max(1, min(int(spec.get('max_b', 10 ** 9)),
                            int(n * float(spec.get('scale_b', 1))) + int(spec.get('offset_b', 1))))
        return f'{first} {second}\n'
    if family == 'THREE_INTS':
        # Fixed-width integer tuples: fast power, graph colouring header,
        # modulo exponent problems. The extra values are derived from n but
        # clamped to the per-problem limits.
        first = max(1, min(int(spec.get('max_a', 10 ** 9)), n))
        second = max(1, min(int(spec.get('max_b', 10 ** 9)), n + int(spec.get('offset_b', 1))))
        third = max(1, min(int(spec.get('max_c', 10 ** 9)), n + int(spec.get('offset_c', 2))))
        return f'{first} {second} {third}\n'
    if family == 'INT_ARRAY':
        # ``extra_values`` covers formats that read n and then n + k numbers,
        # e.g. matrix-chain multiplication reading the n + 1 dimensions.
        # ``max_value`` keeps each element inside the problem's per-element
        # bound while the array itself keeps growing.
        count = n + max(0, int(spec.get('extra_values', 0)))
        high = _value_bound(spec, count)
        values = _permutation(rng, count) if spec.get('kind') == 'permutation' \
            else _ints(rng, count, 1, high)
        return f'{n}\n' + ' '.join(map(str, values)) + '\n'
    if family == 'INT_ARRAY_QUERIES':
        # "n q" header, then n numbers, then q queries. Adds an optional k that
        # rides on the header for "n k + array" problems.
        extra = int(spec.get('header_extra', 0))
        queries = int(spec.get('query_count', n))
        header = f'{n} {extra}' if extra else f'{n} {queries}'
        values = _ints(rng, n, 1, max(2, n))
        rows = [header, ' '.join(map(str, values))]
        if spec.get('query_values') == 'indexes':
            rows.extend(str(rng.randint(0, max(0, n - 1))) for _ in range(queries))
        else:
            rows.extend(str(rng.randint(1, max(2, n))) for _ in range(queries))
        return '\n'.join(rows) + '\n'
    if family == 'INT_ARRAY_WITH_K':
        # "n k" header then n numbers. The second header value is a rank, a
        # window width, a capacity or a piece count: it rides on the header
        # because it is not a separate array. k stays inside 1..n so it is a
        # legal rank or window for every rung.
        k = int(spec.get('k', 0) or 0)
        k = max(1, min(n, k if k > 0 else (n + 1) // 2))
        values = _permutation(rng, n) if spec.get('kind') == 'permutation' \
            else _ints(rng, n, 1, _value_bound(spec, n))
        return f'{n} {k}\n' + ' '.join(map(str, values)) + '\n'
    if family == 'SORTED_ARRAY_QUERIES':
        # "n q" header, a non-decreasing array of n numbers, then q single-value
        # queries (each on its own line). Binary search reads the header, the
        # sorted array and then one target per query.
        queries = int(spec.get('query_count', n))
        values = sorted(_ints(rng, n, 1, max(2, n)))
        rows = [f'{n} {max(1, queries)}', ' '.join(map(str, values))]
        rows.extend(str(rng.randint(1, max(2, n))) for _ in range(max(1, queries)))
        return '\n'.join(rows) + '\n'
    if family == 'INT_ARRAY_OPERATIONS':
        # "n q" header, n numbers, then q operation lines that alternate between
        # a point update ("1 x v") and a range query ("2 l r").
        queries = max(1, int(spec.get('query_count', n)))
        rows = [f'{n} {queries}', ' '.join(map(str, _ints(rng, n, -1000, 1000)))]
        for index in range(queries):
            if index % 2 == 0:
                rows.append(f'1 {rng.randint(1, n)} {rng.randint(-1000, 1000)}')
            else:
                left = rng.randint(1, n)
                rows.append(f'2 {left} {rng.randint(left, n)}')
        return '\n'.join(rows) + '\n'
    if family == 'TWO_INT_ARRAYS':
        high = _value_bound(spec, n)
        first = _ints(rng, n, 1, high)
        second = _ints(rng, n, 1, high)
        return f'{n}\n' + ' '.join(map(str, first)) + '\n' + ' '.join(map(str, second)) + '\n'
    if family == 'INT_ARRAY_ROWS':
        rows = []
        ordered = spec.get('row_kind') == 'ordered'
        for _ in range(n):
            if ordered:
                # Each row is a pair "n_i m_i" with 0 <= m_i <= n_i; combination
                # counting reads the pair as (n, m) and m must not exceed n.
                first = rng.randint(0, n)
                rows.append(f'{first} {rng.randint(0, first)}')
                continue
            start = rng.randint(0, max(1, n))
            rows.append(f'{start} {start + rng.randint(1, max(1, n // 2))}')
        # Knapsack-style problems read "n W" on the first line; the capacity
        # rides along in the spec because it is not a size parameter.
        header_suffix = f' {int(spec["header_extra"])}' if 'header_extra' in spec else ''
        return f'{n}{header_suffix}\n' + '\n'.join(rows) + '\n'
    if family == 'INT_ARRAY_ROWS_TWO_HEADER':
        # "n m" header, then m rows of fixed arity values (edges, ranges,
        # updates). The row count follows n so the ladder scales both parts.
        arity = int(spec.get('arity', 3))
        extra = int(spec.get('header_extra', 0) or 0)
        rows = []
        for _ in range(n):
            values = [rng.randint(1, max(2, n)) for _ in range(max(1, arity))]
            if spec.get('rows_sorted'):
                values[0] = min(values[0], values[1]) if len(values) > 1 else values[0]
            rows.append(' '.join(map(str, values)))
        header = f'{n} {n + extra}' if extra >= 0 else f'{n}'
        return f'{header}\n' + '\n'.join(rows) + '\n'
    if family == 'GRAPH_EDGES':
        # Unweighted graphs read "u v" pairs, weighted ones "u v w"; the bank has
        # both, so the arity comes from the per-problem spec. ``edge_factor``
        # scales the edge count with n and puts "n m" on the header, which is
        # what "n m + m edges" problems read; ``simple`` keeps the graph free of
        # self loops and duplicate edges, as graph colouring requires.
        arity = int(spec.get('edge_arity', 3))
        factor = max(1, int(spec.get('edge_factor', 1)))
        wanted = n * factor
        if spec.get('simple'):
            edges: set[tuple[int, int]] = set()
            wanted = min(wanted, n * (n - 1) // 2)
            attempts = 0
            while len(edges) < wanted and attempts < wanted * 20 + 100:
                u, v = rng.randint(1, n), rng.randint(1, n)
                if u != v:
                    edges.add((min(u, v), max(u, v)))
                attempts += 1
            rows = [f'{u} {v}' for u, v in sorted(edges)]
        else:
            rows = []
            for _ in range(wanted):
                u = rng.randint(1, n)
                v = rng.randint(1, n)
                rows.append(f'{u} {v} {rng.randint(1, 1000)}' if arity == 3 else f'{u} {v}')
        if 'edge_count' in spec:
            header = f'{n} {int(spec["edge_count"])}'
        elif 'edge_factor' in spec:
            header = f'{n} {len(rows)}'
        else:
            header = f'{n}'
        return f'{header}\n' + '\n'.join(rows) + '\n'
    if family == 'GRAPH_COLORING':
        # "n m k" header, then m distinct undirected edges "u v" with u < v.
        # k is an upper bound on usable colours; when k >= n the greedy search
        # never has to backtrack, so the trace measures the search, not luck.
        k = min(n, max(1, int(spec.get('color_count', n) or n)))
        wanted = min(max(0, int(spec.get('edge_factor', 1)) * n), n * (n - 1) // 2)
        edges: set[tuple[int, int]] = set()
        attempts = 0
        while len(edges) < wanted and attempts < wanted * 20 + 100:
            u, v = rng.randint(1, n), rng.randint(1, n)
            if u != v:
                edges.add((min(u, v), max(u, v)))
            attempts += 1
        rows = [f'{n} {len(edges)} {k}'] + [f'{u} {v}' for u, v in sorted(edges)]
        return '\n'.join(rows) + '\n'
    if family == 'GRAPH_TREE_QUERIES':
        # "n root" header, n-1 parent/child edges of a tree, then the query
        # count q and q queries on node pairs (nearest common ancestor and
        # friends). The q line is read separately from the pairs.
        root = int(spec.get('root', 1))
        rows = [f'{n} {root}']
        for node in range(2, n + 1):
            rows.append(f'{rng.randint(1, node - 1)} {node}')
        queries = max(1, int(spec.get('query_count', n)))
        rows.append(str(queries))
        rows.extend(f'{rng.randint(1, n)} {rng.randint(1, n)}' for _ in range(queries))
        return '\n'.join(rows) + '\n'
    if family == 'TWO_STRINGS':
        alphabet = 'abcdefghijklmnopqrstuvwxyz'
        first = _string(rng, n, alphabet)
        second = _string(rng, n, alphabet)
        return f'{first}\n{second}\n'
    if family == 'BIG_TWO_STRINGS':
        # Two decimal integers of n digits each, as strings.
        digits = '123456789'
        first = str(rng.randint(1, 9)) + _string(rng, n - 1, digits)
        second = str(rng.randint(1, 9)) + _string(rng, n - 1, digits)
        return f'{first}\n{second}\n'
    if family == 'STRING_LIST':
        # "n" then n lowercase strings of bounded length, and optionally "q"
        # then q query strings (dictionary problems read a word list first and
        # queries after it). Each query is a prefix of one of the words, so the
        # lookup actually walks the structure built from the list.
        alphabet = 'abcdefghijklmnopqrstuvwxyz'
        length = max(1, int(spec.get('word_length', max(1, 8))))
        words = [_string(rng, rng.randint(1, length), alphabet) for _ in range(n)]
        rows = [str(n)] + words
        queries = n if spec.get('queries') else max(0, int(spec.get('query_count', 0) or 0))
        if queries:
            rows.append(str(queries))
            for _ in range(queries):
                word = words[rng.randrange(n)]
                rows.append(word[:rng.randint(1, len(word))])
        return '\n'.join(rows) + '\n'
    if family == 'STRING_RANGE_QUERIES':
        # A lowercase string of n characters, then the query count q, then q
        # lines of four 1-based positions "l1 r1 l2 r2" with l <= r (substring
        # hash comparison and friends).
        alphabet = 'abcdefghijklmnopqrstuvwxyz'
        queries = max(1, int(spec.get('query_count', n)))
        rows = [_string(rng, n, alphabet), str(queries)]
        for _ in range(queries):
            left = rng.randint(1, n)
            second_left = rng.randint(1, n)
            rows.append(f'{left} {rng.randint(left, n)} '
                        f'{second_left} {rng.randint(second_left, n)}')
        return '\n'.join(rows) + '\n'
    if family == 'ONE_STRING':
        alphabet = spec.get('alphabet', 'abcdefghijklmnopqrstuvwxyz')
        return _string(rng, n, alphabet) + '\n'
    if family == 'GRAPH_EDGE_QUERIES':
        # "n m" header, m edge pairs, then the query count q and q node pairs
        # (connected-components queries: union-find over a plain graph).
        factor = max(1, int(spec.get('edge_factor', 1)))
        edge_count = min(n * factor, n * (n - 1) // 2)
        rows = [f'{n} {edge_count}']
        rows.extend(f'{rng.randint(1, n)} {rng.randint(1, n)}' for _ in range(edge_count))
        queries = max(1, int(spec.get('query_count', n)))
        rows.append(str(queries))
        rows.extend(f'{rng.randint(1, n)} {rng.randint(1, n)}' for _ in range(queries))
        return '\n'.join(rows) + '\n'
    if family == 'POSTFIX_EXPRESSION':
        # One line of postfix tokens: "x1 x2 + x3 + ... xk". A left fold keeps
        # the stack at depth two, so the expression is always valid and the
        # evaluator does one push or one operate per token.
        operands = max(2, n)
        values = _ints(rng, operands, 1, 1000)
        tokens = [str(values[0]), str(values[1])]
        for index in range(2, operands):
            tokens.append(rng.choice(spec.get('operators', ('+',))))
            tokens.append(str(values[index]))
        return ' '.join(tokens) + '\n'
    if family == 'STACK_OPERATIONS':
        # "q" then q operation lines. The cycle push, push, front, pop keeps the
        # queue non-empty, so a correct implementation really transfers and pops
        # instead of printing "empty".
        queries = max(1, int(spec.get('query_count', n)))
        rows = [str(queries)]
        for index in range(queries):
            step = index % 4
            if step <= 1:
                rows.append(f'push {rng.randint(-2 ** 31, 2 ** 31 - 1)}')
            elif step == 2:
                rows.append('front')
            else:
                rows.append('pop')
        return '\n'.join(rows) + '\n'
    if family == 'GRID':
        rows = []
        for _ in range(n):
            row = ['.'] * n
            for column in range(n):
                row[column] = '.' if rng.random() > 0.2 else '#'
            row[0] = '.'
            row[-1] = '.'
            rows.append(''.join(row))
        return f'{n} {n}\n' + '\n'.join(rows) + '\n'
    if family == 'GRID_WITH_WORD':
        # Grid plus one word that certainly exists as an orthogonal path, so the
        # search algorithm actually runs instead of returning early.
        rows = [['.'] * n for _ in range(n)]
        path = ''.join(rng.choice('abc') for _ in range(max(2, n // 2)))
        row = 1 if n > 2 else 0
        for index, char in enumerate(path):
            column = min(index, n - 1)
            rows[row % n][column] = char
        text = '\n'.join(''.join(line) for line in rows)
        return f'{n} {n}\n{text}\n{path}\n'
    if family == 'MATRIX':
        rows = [f'{n} {n}']
        for _ in range(n):
            rows.append(' '.join(str(value) for value in _ints(rng, n, -100, 100)))
        return '\n'.join(rows) + '\n'
    if family == 'TRIANGLE_ROWS':
        # "n" followed by 1 + 2 + ... + n values.
        values: list[int] = []
        for width in range(1, n + 1):
            values.extend(str(rng.randint(-100, 100)) for _ in range(width))
        return f'{n}\n' + '\n'.join(values) + '\n'
    if family == 'KNAPSACK':
        # "n W" then n "weight value" rows.
        capacity = int(spec.get('capacity', max(1, 10 * n)))
        rows = [f'{n} {capacity}']
        for _ in range(n):
            weight = rng.randint(1, max(1, capacity))
            rows.append(f'{weight} {rng.randint(1, 1000)}')
        return '\n'.join(rows) + '\n'
    if family == 'FIXED':
        return str(spec.get('text', ''))
    raise ProfileError(f'unsupported family {family}')


def _geometric_ladder(start: int, limit: int, count: int) -> tuple[int, ...]:
    """``count`` sizes from ``start`` to ``limit`` in log space (both included)."""
    start = max(4, min(start, limit))
    if limit <= start:
        return (start,)
    ratio = (limit / start) ** (1 / max(1, count - 1))
    values = {min(limit, max(start, int(round(start * ratio ** step))))
              for step in range(count)}
    return tuple(sorted(values))


def _even_ladder(start: int, limit: int, steps: int) -> tuple[int, ...]:
    """Evenly spaced sizes from ``start`` to ``limit``, always including both."""
    values = {start, limit}
    span = limit - start
    for index in range(1, steps):
        values.add(start + round(span * index / steps))
    return tuple(sorted(size for size in values if 4 <= size <= limit))


def plan_sizes(max_n: int, *, cap: int = 16384,
               value_family: bool = False) -> tuple[int, ...]:
    """Choose the input sizes for one problem.

    Problems with a small size limit (Hanoi 10, permutations 8) get an evenly
    spaced ladder from 4 to the limit: doubling would leave only two points and
    fast-growing programs need adjacent points to show their ratio. Problems
    without a tight limit get a doubling ladder, which is what separates
    polynomial classes from each other. A limit between 96 and 256 leaves fewer
    than four doublings (matrix chain n <= 100, word search 6x6), so it falls
    back to the same even ramp instead of a two-point ladder.
    """
    limit = max(4, int(max_n))
    if limit <= SMALL_MAX_N:
        return _even_ladder(max(4, limit // 8), limit, 7)
    if value_family:
        sizes = [size for size in VALUE_SIZES if size <= limit]
        return tuple(sizes) if len(sizes) >= 4 else tuple(sorted(set(
            [size for size in DEFAULT_SIZES if size <= limit] or [limit])))
    sizes = [size for size in DEFAULT_SIZES if size <= min(limit, cap)]
    if len(sizes) < 4:
        return _even_ladder(4, limit, 6)
    if len(sizes) < 6:
        # A five-rung ladder lets a three-parameter fit imitate a neighbouring
        # class. Problems whose own limit stops below 4096 (for example
        # "n <= 1000") get a finer geometric ramp instead of five doublings.
        return _geometric_ladder(max(32, sizes[0]), limit, 7)
    return tuple(sorted(set(sizes)))


def ladder(family: str, seed: int, spec: dict | None = None,
           sizes: tuple[int, ...] | None = None) -> list[Rung]:
    if family not in FAMILIES:
        raise ProfileError(f'unknown family {family!r}')
    if family == 'EXISTING_CASES':
        return []
    spec = spec or {}
    chosen = tuple(sizes) if sizes else plan_sizes(
        int(spec.get('max_n', 0) or 4096),
        value_family=family in VALUE_FAMILIES)
    rungs: list[Rung] = []
    for size in chosen:
        text = generate(family, size, seed, spec)
        if len(text.encode('utf-8')) > MAX_INPUT_BYTES:
            break
        rungs.append(Rung(n=size, input_text=text))
    return rungs
