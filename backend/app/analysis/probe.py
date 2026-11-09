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

import ast
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


def _array_values(rng: random.Random, count: int, spec: dict) -> list[int]:
    """Generate the declared value domain before applying an input distribution."""
    low = int(spec.get('value_min', 1))
    high = int(spec.get('value_max', _value_bound(spec, count)))
    if spec.get('sum_max') is not None and count:
        high = min(high, int(spec['sum_max']) // count)
    if low > high:
        raise ProfileError('数组元素下界超过上界')
    if spec.get('unique'):
        if count > high - low + 1:
            raise ProfileError('互异元素的取值范围不足以容纳该规模')
        values = rng.sample(range(low, high + 1), count)
    elif spec.get('kind') == 'permutation':
        values = _permutation(rng, count)
    else:
        values = _ints(rng, count, low, high)
    order = spec.get('order') or spec.get('distribution', 'random')
    if order in ('ascending', 'descending'):
        values.sort(reverse=order == 'descending')
    return values


def bound_value(expression: int | str, variables: dict | None = None) -> int:
    """Evaluate a bounded integer expression, never Python calls or attributes."""
    variables = variables or {}
    source = str(expression).replace('^', '**')
    if len(source) > 120:
        raise ProfileError('约束表达式过长')
    tree = ast.parse(source, mode='eval')
    if len(list(ast.walk(tree))) > 50:
        raise ProfileError('约束表达式过于复杂')
    def visit(node):
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            value = node.value
        elif isinstance(node, ast.Name):
            value = variables[node.id]
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
            value = visit(node.operand) * (-1 if isinstance(node.op, ast.USub) else 1)
        elif isinstance(node, ast.BinOp):
            left, right = visit(node.left), visit(node.right)
            if isinstance(node.op, ast.Add): value = left + right
            elif isinstance(node.op, ast.Sub): value = left - right
            elif isinstance(node.op, ast.Mult): value = left * right
            elif isinstance(node.op, ast.Pow) and 0 <= right <= 64: value = left ** right
            elif isinstance(node.op, (ast.Div, ast.FloorDiv)) and right and (
                    isinstance(node.op, ast.FloorDiv) or left % right == 0): value = left // right
            else: raise ProfileError('不支持的整数约束运算')
        else:
            raise ProfileError('约束中包含未支持的表达式')
        if abs(value) > 2**63 or int(value) != value:
            raise ProfileError('整数约束超出支持范围')
        return int(value)
    return visit(tree.body)


def _field_bounds(field: dict, variables: dict, *, partial: bool = False) -> tuple[int, int]:
    result = []
    for key, aggregate in (('min', max), ('max', min)):
        expressions = field[key] if isinstance(field[key], list) else [field[key]]
        values = []
        for expression in expressions:
            try:
                values.append(bound_value(expression, variables))
            except KeyError:
                if not partial:
                    raise ProfileError('约束引用了未读入的参数') from None
        if not values:
            raise ProfileError('字段缺少可确定的数值边界')
        result.append(aggregate(values))
    if result[0] > result[1]:
        raise ProfileError('字段约束没有可行值')
    return tuple(result)


def _check_relations(relations: list, variables: dict) -> bool:
    for left, strict, right in relations:
        a, b = bound_value(left, variables), bound_value(right, variables)
        if a > b or strict and a == b:
            return False
    return True


def _layout_input(spec: dict, n: int, seed: int) -> str:
    """Compose existing input families from typed lines and bounded repetitions."""
    rng = random.Random(f'{seed}:layout:{n}:{spec.get("distribution", "random")}')
    lines, texts = [], {}
    def emit(nodes, variables):
        for node in nodes:
            kind = node['kind']
            if kind == 'repeat':
                for index in range(bound_value(node['count'], variables)):
                    emit(node['body'], dict(variables, _row=index))
            elif kind == 'edges':
                vertices = variables[node['vertices']]
                count = bound_value(node['count'], variables)
                options = dict(node['options'], target_edges=count)
                generated = generate('GRAPH_EDGES', vertices, rng.randrange(2**32), options)
                lines.extend(generated.splitlines()[1:])
            elif kind == 'ints':
                for _ in range(100):
                    local = dict(variables)
                    values = []
                    for field in node['fields']:
                        low, high = _field_bounds(field, local, partial=True)
                        if spec.get('distribution') == 'within_capacity' and field.get('capacity_parameter'):
                            capacity = local[field['capacity_parameter']]
                            if low <= capacity: high = min(high, capacity)
                        value = bound_value(field['value'], local) if 'value' in field else rng.randint(low, high)
                        value = max(low, min(high, value))
                        local[field['name']] = value
                        values.append(value)
                    if all(start <= local[field['name']] <= end for field in node['fields']
                           for start, end in [_field_bounds(field, local)]) and _check_relations(node.get('relations', []), local):
                        break
                else:
                    raise ProfileError('字段间约束在尝试预算内没有得到可行值')
                variables.update(local)
                lines.append(' '.join(map(str, values)))
            elif kind == 'array':
                count = bound_value(node['count'], variables)
                low, high = _field_bounds(node, variables)
                options = dict(node, value_min=low, value_max=high, distribution=spec.get('distribution', 'random'))
                if 'sum_max' in node:
                    options['sum_max'] = bound_value(node['sum_max'], variables)
                lines.append(' '.join(map(str, _array_values(rng, count, options))))
            elif kind == 'text':
                length = bound_value(node['length'], variables)
                alphabet = node['alphabet']
                key = (length, alphabet, node.get('no_leading_zero', False))
                if spec.get('distribution') == 'identical' and key in texts:
                    value = texts[key]
                else:
                    value = _string(rng, length, alphabet)
                    if spec.get('distribution') == 'repeated': value = alphabet[0] * length
                    if node.get('no_leading_zero') and length > 1:
                        value = rng.choice('123456789') + value[1:]
                    texts[key] = value
                if node.get('grid_endpoints'):
                    if variables['_row'] == 0: value = '.' + value[1:]
                    if variables['_row'] == variables[node['grid_rows']] - 1: value = value[:-1] + '.'
                if node.get('bind_length'):
                    variables[node['bind_length']] = len(value)
                lines.append(value)
            else:
                raise ProfileError('未支持的输入布局节点')
    emit(spec['layout'], {'_scale': n})
    return '\n'.join(lines) + '\n'


def _validate_layout(text: str, spec: dict, size: int | None) -> None:
    lines, position = text.splitlines(), 0
    text_lengths = {}
    def read(nodes, variables):
        nonlocal position
        for node in nodes:
            kind = node['kind']
            if kind == 'repeat':
                count = bound_value(node['count'], variables)
                if not 0 <= count <= len(lines) - position:
                    raise ProfileError('重复记录数量与输入行数不符')
                for index in range(count):
                    read(node['body'], dict(variables, _row=index))
                continue
            if kind == 'edges':
                count = bound_value(node['count'], variables)
                if not 0 <= count <= len(lines) - position: raise ProfileError('边列表行数不符')
                vertices = variables[node['vertices']]
                edge_text = f'{vertices} {count}\n' + '\n'.join(lines[position:position + count]) + '\n'
                validate_input('GRAPH_EDGES', edge_text, dict(node['options'], min_n=1, max_n=10**18))
                position += count
                continue
            if position >= len(lines):
                raise ProfileError('输入缺少声明的记录行')
            line = lines[position]
            position += 1
            if kind == 'ints':
                values = list(map(int, line.split()))
                if len(values) != len(node['fields']): raise ProfileError('整数字段数量不符')
                variables.update((field['name'], value) for field, value in zip(node['fields'], values))
                for field, value in zip(node['fields'], values):
                    low, high = _field_bounds(field, variables)
                    if not low <= value <= high: raise ProfileError('整数字段超出约束范围')
                    if size is not None and field.get('value') == '_scale' and value != size:
                        raise ProfileError('实际规模与档位不一致')
                if not _check_relations(node.get('relations', []), variables):
                    raise ProfileError('字段间大小关系不符')
            elif kind == 'array':
                values = list(map(int, line.split()))
                low, high = _field_bounds(node, variables)
                if len(values) != bound_value(node['count'], variables): raise ProfileError('数组长度不符')
                if any(not low <= value <= high for value in values): raise ProfileError('数组元素超出范围')
                if node.get('unique') and len(set(values)) != len(values): raise ProfileError('数组元素不互异')
                if node.get('order') and values != sorted(values, reverse=node['order'] == 'descending'):
                    raise ProfileError('数组排序方向不符')
                if 'sum_max' in node and sum(values) > bound_value(node['sum_max'], variables):
                    raise ProfileError('数组元素和超出上限')
            elif kind == 'text':
                low, high = _field_bounds(node, variables)
                if not low <= len(line) <= high or set(line) - set(node['alphabet']):
                    raise ProfileError('文本长度或字符集不符')
                if node.get('exact') and len(line) != bound_value(node['length'], variables):
                    raise ProfileError('文本长度与头部参数不一致')
                if size is not None and node['length'] == '_scale' and len(line) != size:
                    raise ProfileError('字符串长度与档位不一致')
                if node.get('no_leading_zero') and len(line) > 1 and line[0] == '0':
                    raise ProfileError('十进制表示含有多余前导零')
                if node.get('tag'):
                    text_lengths[node['tag']] = text_lengths.get(node['tag'], 0) + len(line)
                if node.get('bind_length'):
                    variables[node['bind_length']] = len(line)
                if node.get('grid_endpoints') and (
                        variables['_row'] == 0 and line[0] != '.' or
                        variables['_row'] == variables[node['grid_rows']] - 1 and line[-1] != '.'):
                    raise ProfileError('网格端点不是可通行字符')
            else:
                raise ProfileError('未支持的输入布局节点')
    read(spec['layout'], {'_scale': size} if size is not None else {})
    if any(line.strip() for line in lines[position:]):
        raise ProfileError('声明的布局之后还有未识别的输入')
    for limit in spec.get('length_limits', []):
        if text_lengths.get(limit['tag'], 0) > limit['max']:
            raise ProfileError('字符串总长度超出上限')


def generate(family: str, n: int, seed: int, spec: dict | None = None) -> str:
    """Return one input text for the given family and size ``n``."""
    spec = spec or {}
    rng = random.Random(f'{seed}:{family}:{n}')
    n = max(1, int(n))
    if spec.get('layout'):
        return _layout_input(spec, n, seed)
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
        values = _array_values(rng, count, spec)
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
        k = int(spec.get('header_value', spec.get('k', 0)) or 0)
        if 'header_value' not in spec:
            k = max(int(spec.get('k_min', 1)), min(n, k if k > 0 else (n + 1) // 2))
        values = _array_values(rng, n, spec)
        return f'{n} {k}\n' + ' '.join(map(str, values)) + '\n'
    if family == 'SORTED_ARRAY_QUERIES':
        # "n q" header, a non-decreasing array of n numbers, then q single-value
        # queries (each on its own line). Binary search reads the header, the
        # sorted array and then one target per query.
        queries = int(spec.get('query_count', n))
        values = sorted(_array_values(rng, n, spec))
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
        if 'row_bounds' in spec:
            bounds = spec['row_bounds']
            rows = []
            for _ in range(n):
                values = [rng.randint(int(low), int(high)) for low, high in bounds]
                if spec.get('ordered_rows'):
                    first = rng.randint(int(bounds[0][0]), min(int(bounds[0][1]), int(bounds[1][1]) - 1))
                    values = [first, rng.randint(max(first + 1, int(bounds[1][0])), int(bounds[1][1]))]
                rows.append(' '.join(map(str, values)))
            return f'{n}\n' + '\n'.join(rows) + '\n'
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
        if spec.get('adaptive_graph'):
            directed = bool(spec.get('directed'))
            tree = bool(spec.get('tree'))
            maximum = n * (n - 1) // (1 if directed and not spec.get('acyclic') else 2)
            wanted = int(spec['target_edges']) if 'target_edges' in spec else n - 1 if tree else min(maximum, n * int(spec.get('edge_factor', 2)),
                                             int(spec.get('max_edges', maximum)))
            minimum = max(n - 1 if spec.get('connected') else 0, int(spec.get('min_edges', 0)))
            if wanted < minimum or wanted > maximum or tree and wanted != n - 1:
                raise ProfileError('边数约束无法满足')
            edges = {(rng.randint(1, node - 1), node) for node in range(2, n + 1)} \
                if spec.get('connected') or tree else set()
            # A bounded fill plus deterministic fallback avoids rejection loops
            # when a small graph is nearly complete.
            for _ in range(wanted * 8 + 20):
                if len(edges) >= wanted:
                    break
                u, v = rng.randint(1, n), rng.randint(1, n)
                if u != v:
                    edges.add((u, v) if directed and not spec.get('acyclic') else (min(u, v), max(u, v)))
            if len(edges) < wanted:
                for u in range(1, n + 1):
                    for v in range(1 if directed and not spec.get('acyclic') else u + 1, n + 1):
                        if u != v:
                            edges.add((u, v))
                        if len(edges) >= wanted:
                            break
                    if len(edges) >= wanted:
                        break
            rows = [f'{n} {len(edges)}']
            for u, v in sorted(edges):
                weight = f" {rng.randint(int(spec.get('weight_min', 1)), int(spec.get('weight_max', 100)))}" \
                    if int(spec.get('edge_arity', 2)) == 3 else ''
                rows.append(f'{u} {v}{weight}')
            return '\n'.join(rows) + '\n'
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
        alphabet = spec.get('alphabet', 'abcdefghijklmnopqrstuvwxyz')
        first = _string(rng, n, alphabet)
        second = first if spec.get('distribution') == 'identical' else _string(rng, n, alphabet)
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
        text = _string(rng, n, alphabet)
        if spec.get('distribution') == 'repeated':
            text = alphabet[0] * n
        return (f'{n}\n' if spec.get('length_header') else '') + text + '\n'
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
            rows.append(' '.join(str(value) for value in _ints(
                rng, n, int(spec.get('value_min', -100)), int(spec.get('value_max', 100)))))
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


def validate_input(family: str, text: str, spec: dict, *, size: int | None = None) -> None:
    """Check an automatically inferred schema independently of program exit codes.

    Only the formats inferred by profiles.adaptive_candidates are accepted here.
    Stored, manually seeded families keep their existing generation contract.
    """
    if spec.get('layout'):
        _validate_layout(text, spec, size)
        return
    lines = [line.strip() for line in text.strip().splitlines()]
    low, high = int(spec['min_n']), int(spec['max_n'])
    if family in ('ONE_STRING', 'TWO_STRINGS'):
        if spec.get('length_header'):
            if len(lines) != 2 or int(lines[0]) != len(lines[1]):
                raise ProfileError('字符串长度与首行不一致')
            lines = lines[1:]
        if len(lines) != (2 if family == 'TWO_STRINGS' else 1):
            raise ProfileError('字符串行数不一致')
        if any(not low <= len(line) <= high or set(line) - set(spec['alphabet']) for line in lines):
            raise ProfileError('字符串长度或字符集不符合约束')
        if size is not None and any(len(line) != size for line in lines):
            raise ProfileError('字符串实际规模与档位不一致')
        return
    rows = [list(map(int, line.split())) for line in lines]
    if not rows or not rows[0]:
        raise ProfileError('缺少整数头部')
    n = rows[0][0]
    if not low <= n <= high or size is not None and n != size:
        raise ProfileError('实际规模不符合声明')
    if family == 'SINGLE_INT':
        if len(rows) != 1 or len(rows[0]) != 1:
            raise ProfileError('单整数格式不符')
        return
    if family == 'GRAPH_EDGES':
        if len(rows[0]) != 2:
            raise ProfileError('图头部需要两个整数')
        m = rows[0][1]
        if len(rows) != m + 1 or not int(spec.get('min_edges', 0)) <= m <= int(spec.get('max_edges', 10**12)):
            raise ProfileError('边数不符')
        seen, adjacency = set(), {node: set() for node in range(1, n + 1)}
        for edge in rows[1:]:
            if len(edge) != spec['edge_arity']:
                raise ProfileError('边的字段数不符')
            u, v = edge[:2]
            key = (u, v) if spec['directed'] else (min(u, v), max(u, v))
            if not 1 <= u <= n or not 1 <= v <= n or spec.get('simple') and (u == v or key in seen):
                raise ProfileError('边端点、自环或重边违反约束')
            if size is not None and spec.get('acyclic') and u >= v:
                raise ProfileError('有向无环图必须按拓扑顺序生成')
            if len(edge) == 3 and not spec['weight_min'] <= edge[2] <= spec['weight_max']:
                raise ProfileError('边权超出范围')
            seen.add(key)
            adjacency[u].add(v)
            adjacency[v].add(u)
        if spec.get('connected') or spec.get('tree'):
            reached, pending = {1}, [1]
            while pending:
                for node in adjacency[pending.pop()]:
                    if node not in reached:
                        reached.add(node)
                        pending.append(node)
            if len(reached) != n or spec.get('tree') and m != n - 1:
                raise ProfileError('连通性或树的边数不符合约束')
        return
    if family == 'MATRIX':
        if len(rows[0]) != 2 or not low <= rows[0][1] <= high:
            raise ProfileError('矩阵列数超出范围')
        width = rows[0][1]
        if len(rows) != n + 1 or any(len(row) != width for row in rows[1:]):
            raise ProfileError('矩阵实际行列数不符')
        values = [value for row in rows[1:] for value in row]
    elif family == 'INT_ARRAY_ROWS':
        if len(rows[0]) != 1 or len(rows) != n + 1:
            raise ProfileError('记录行数不符')
        for row in rows[1:]:
            if len(row) != len(spec['row_bounds']) or any(
                    not start <= value <= end for value, (start, end) in zip(row, spec['row_bounds'])):
                raise ProfileError('记录字段或范围不符')
            if spec.get('ordered_rows') and row[0] >= row[1]:
                raise ProfileError('区间端点顺序不符')
        return
    else:
        header_count = 1 if family == 'INT_ARRAY' else 2
        if len(rows[0]) != header_count or len(rows) < 2 or len(rows[1]) != n:
            raise ProfileError('数组头部或元素数量不符')
        values = rows[1]
        if family == 'SORTED_ARRAY_QUERIES':
            if len(rows) != rows[0][1] + 2 or any(len(row) != 1 for row in rows[2:]):
                raise ProfileError('查询数量不符')
        elif len(rows) != 2:
            raise ProfileError('数组之后存在未识别的输入')
        if family == 'INT_ARRAY_WITH_K':
            k = rows[0][1]
            if 'header_value' in spec:
                # Stored cases can use other legal values of the fixed parameter.
                if not spec['header_min'] <= k <= spec['header_max']:
                    raise ProfileError('第二个参数超出范围')
            elif 'header_value' not in spec and not spec.get('k_min', 1) <= k <= n:
                raise ProfileError('排名或窗口参数超出范围')
    if any(not spec['value_min'] <= value <= spec['value_max'] for value in values):
        raise ProfileError('元素超出取值范围')
    if spec.get('unique') and len(set(values)) != len(values):
        raise ProfileError('数组元素必须互异')
    if spec.get('sum_max') is not None and sum(values) > spec['sum_max']:
        raise ProfileError('数组元素和超出上限')
    if spec.get('order') == 'ascending' and values != sorted(values):
        raise ProfileError('数组必须非递减')
    if spec.get('order') == 'descending' and values != sorted(values, reverse=True):
        raise ProfileError('数组必须非递增')


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
    chosen = tuple(sizes) if sizes is not None else tuple(spec['sizes']) if 'sizes' in spec else plan_sizes(
        int(spec.get('max_n', 0) or 4096),
        value_family=family in VALUE_FAMILIES)
    rungs: list[Rung] = []
    for size in chosen:
        text = generate(family, size, seed, spec)
        if len(text.encode('utf-8')) > MAX_INPUT_BYTES:
            break
        rungs.append(Rung(n=size, input_text=text))
    return rungs
