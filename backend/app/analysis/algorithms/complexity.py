"""Time/space complexity estimation from source structure and measured growth.

Two independent estimators, combined into one verdict:

* Static analysis walks the syntax tree (Python) or a lexical block structure
  (C/C++/Java) and derives the nesting depth of loops, logarithmic halving,
  recursion shape and memory allocation sites. It always produces an answer,
  but it reasons about the code shape, not about a particular input.
* Empirical growth runs the program on a ladder of generated input sizes,
  records wall time and peak child memory, and fits ``t = a * f(n)`` over a
  candidate family of complexity classes.

Agreement raises confidence; disagreement is reported instead of silently
picking the nicer number. Nothing here imports FastAPI or SQLAlchemy: the
module is a pure function library so the same code runs in tests, in the
worker and in an offline experiment.
"""

from __future__ import annotations

import ast
import math
import re
from dataclasses import dataclass, field
from typing import Iterable

# Ordered from cheapest to most expensive; index is used for comparisons.
TIME_CLASSES = ('O(1)', 'O(log n)', 'O(n)', 'O(n log n)', 'O(n^2)', 'O(n^2 log n)', 'O(n^3)', 'O(2^n)')
SPACE_CLASSES = ('O(1)', 'O(log n)', 'O(n)', 'O(n^2)')
CLASS_RANK = {name: index for index, name in enumerate(TIME_CLASSES)}
CONFIDENCE = ('LOW', 'MEDIUM', 'HIGH')

# f(n) for each class, used by the least-squares fit and by the frontend curve.
GROWTH_FUNCTIONS = {
    'O(1)': lambda n: 1.0,
    'O(log n)': lambda n: math.log2(n + 2),
    'O(n)': lambda n: float(n),
    'O(n log n)': lambda n: n * math.log2(n + 2),
    'O(n^2)': lambda n: float(n) ** 2,
    'O(n^2 log n)': lambda n: (float(n) ** 2) * math.log2(n + 2),
    'O(n^3)': lambda n: float(n) ** 3,
    'O(2^n)': lambda n: 2.0 ** min(n, 60),
}

PYTHON_LANGUAGES = {'python', 'python3', 'python3.11', 'python3.12', 'python3.13', 'python3.14', 'py'}
C_LIKE_LANGUAGES = {'c', 'c17', 'gcc', 'cpp', 'c++', 'cpp17', 'g++', 'cc', 'java', 'java17',
                    'openjdk', 'c-like'}

_SORT_CALLS = {'sort', 'sorted', 'heapify', 'heappush', 'heappop', 'nlargest', 'nsmallest', 'bisect'}
_RECURSIVE_OK = True


def language_family(language: str | None) -> str:
    if not language:
        return ''
    value = language.strip().lower()
    if value in PYTHON_LANGUAGES:
        return 'python'
    if value in C_LIKE_LANGUAGES:
        return 'c-like'
    return ''


def _greater(left: str, right: str) -> str:
    return left if CLASS_RANK[left] >= CLASS_RANK[right] else right


def _next_class(name: str) -> str:
    rank = CLASS_RANK[name]
    return TIME_CLASSES[min(rank + 1, len(TIME_CLASSES) - 1)]


# --------------------------------------------------------------------- static


@dataclass
class StaticAnalysis:
    language_family: str
    time_class: str
    space_class: str
    confidence: str
    evidence: list[dict] = field(default_factory=list)
    loop_depth: int = 0
    max_loop_lines: list[int] = field(default_factory=list)
    recursive: bool = False
    recursion_kind: str | None = None
    logarithmic_loops: int = 0
    sorts: int = 0
    dynamic_allocations: int = 0
    matrix_allocations: int = 0
    notes: list[str] = field(default_factory=list)

    def to_payload(self) -> dict:
        return {
            'time_class': self.time_class,
            'space_class': self.space_class,
            'confidence': self.confidence,
            'evidence': self.evidence,
            'loop_depth': self.loop_depth,
            'max_loop_lines': self.max_loop_lines,
            'recursive': self.recursive,
            'recursion_kind': self.recursion_kind,
            'logarithmic_loops': self.logarithmic_loops,
            'sorts': self.sorts,
            'dynamic_allocations': self.dynamic_allocations,
            'notes': self.notes,
        }


class _CostStack:
    """Multiplicative cost of the currently open loops.

    A plain ``for`` loop multiplies the work by ``n``; a ``while`` loop whose own
    bound halves multiplies by ``log n``. Keeping them as a pair (polynomial
    degree, log count) is enough for every class the platform reports, and it
    avoids the classic mistake of treating a binary search as ``O(n log n)``.
    """

    def __init__(self):
        self.poly = 0
        self.log = 0

    def push(self, kind: str) -> None:
        if kind == 'log':
            self.log += 1
        else:
            self.poly += 1

    def pop(self, kind: str) -> None:
        if kind == 'log':
            self.log = max(0, self.log - 1)
        else:
            self.poly = max(0, self.poly - 1)

    def snapshot(self) -> tuple[int, int]:
        return self.poly, self.log

    @staticmethod
    def better(left: tuple[int, int], right: tuple[int, int]) -> tuple[int, int]:
        rank = _classify(left)
        other = _classify(right)
        return left if CLASS_RANK[rank] >= CLASS_RANK[other] else right


def _classify(shape: tuple[int, int]) -> str:
    poly, log = shape
    if poly <= 0:
        return 'O(log n)' if log else 'O(1)'
    if poly == 1:
        return 'O(n log n)' if log else 'O(n)'
    if poly == 2:
        return 'O(n^2 log n)' if log else 'O(n^2)'
    if poly >= 3:
        return 'O(n^3)'
    return 'O(1)'


# Calls that aggregate a whole container. Only these count as one linear pass at
# the top level; cheap calls (append, len, split, print) must never be counted,
# or every input parse would look linear.
_WHOLE_CONTAINER_CALLS = frozenset({'sum', 'max', 'min', 'join', 'sorted', 'any', 'all',
                                    'reversed', 'nlargest', 'nsmallest'})
_REDUCTION_NAMES = frozenset({
    'n', 'size', 'length', 'count', 'l', 'r', 'lo', 'hi', 'left', 'right', 'mid', 'low',
    'high', 'm', 'k', 'w', 'total', 'num', 'amount', 'budget', 'capacity', 'p', 'q', 'limit',
})


class _PythonVisitor(ast.NodeVisitor):
    """Collect structural facts about one Python source file.

    The visitor records facts and :func:`analyze_python` derives the class, so
    each rule stays small and testable. A nested function body restarts the loop
    scope, because its loops are not nested inside the caller's loops.
    """

    def __init__(self):
        self.stack = _CostStack()
        self.best_shape: tuple[int, int] = (0, 0)
        self.max_loop_depth = 0
        self.max_loop_lines: list[int] = []
        self.logarithmic_loops = 0
        self.sorts = 0
        self.reductions = 0
        self.dynamic_allocations = 0
        self.matrix_allocations = 0
        self.call_counts: dict[str, int] = {}
        self.function_bodies: dict[str, ast.AST] = {}
        self.function_loops: set[str] = set()
        self.function_sorts: set[str] = set()
        self.current_function: str | None = None
        self.evidence: list[dict] = []

    # -- helpers -----------------------------------------------------
    def _record(self, shape: tuple[int, int]) -> None:
        self.best_shape = _CostStack.better(self.best_shape, shape)

    def _note(self, line: int, reason: str, kind: str) -> None:
        self.evidence.append({'line': line, 'reason': reason, 'kind': kind})

    # -- structure -----------------------------------------------------
    def _visit_function(self, node) -> None:
        previous_name = self.current_function
        saved_stack = self.stack
        self.current_function = node.name
        self.stack = _CostStack()
        self.function_bodies[node.name] = node
        for child in node.body:
            self.visit(child)
        calls = self.call_counts.get(node.name, 0)
        if calls:
            if node.name in self.function_loops:
                self._note(node.lineno, f'递归函数 {node.name} 每层含循环，递归与循环相乘',
                           'RECURSION_WITH_LOOP')
            if node.name in self.function_sorts:
                self._note(node.lineno, f'递归函数 {node.name} 内有排序，贡献额外 log n 因子',
                           'RECURSION_WITH_SORT')
        self.stack = saved_stack
        self.current_function = previous_name

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node)

    visit_AsyncFunctionDef = visit_FunctionDef

    def _visit_loop(self, node, kind: str, weight: str) -> None:
        self.stack.push(weight)
        if self.current_function is not None:
            self.function_loops.add(self.current_function)
        self.max_loop_depth = max(self.max_loop_depth, self.stack.poly + self.stack.log)
        if self.stack.poly + self.stack.log == self.max_loop_depth:
            self.max_loop_lines.append(node.lineno)
        self._record(self.stack.snapshot())
        for child in node.body:
            self.visit(child)
        for child in node.orelse:
            self.visit(child)
        self.stack.pop(weight)

    def visit_For(self, node: ast.For) -> None:
        self._visit_loop(node, 'for', 'n')

    visit_AsyncFor = visit_For

    def visit_While(self, node: ast.While) -> None:
        # ``while lo < hi: mid = (lo+hi)//2`` is logarithmic: the loop's own
        # bound shrinks by half, so it is not an n-times loop.
        weight = 'log' if _loop_halves(node) else 'n'
        self._visit_loop(node, 'while', weight)

    # -- reduction detection --------------------------------------------
    def visit_Assign(self, node: ast.Assign) -> None:
        names = {target.id for target in node.targets if isinstance(target, ast.Name)}
        if names & _REDUCTION_NAMES and _halving_expression(node.value):
            self.reductions += 1
            self._note(node.lineno, '规模变量按 2 倍收缩', 'HALVING')
            if self.stack.poly + self.stack.log == 0:
                self._record((0, 1))
        for child in ast.iter_child_nodes(node):
            self.visit(child)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        if isinstance(node.op, (ast.FloorDiv, ast.RShift)):
            self.reductions += 1
            self._note(node.lineno, '对规模变量做整除或右移，属于对数收缩', 'HALVING')
        for child in ast.iter_child_nodes(node):
            self.visit(child)

    # -- calls / allocation ---------------------------------------------
    def visit_Call(self, node: ast.Call) -> None:
        name = _call_name(node.func)
        if name in ('list', 'set', 'dict', 'tuple', 'sorted') and node.args \
                and not isinstance(node.args[0], (ast.List, ast.Set, ast.Dict, ast.Tuple, ast.Constant)):
            # ``list(map(int, input().split()))`` materialises a container whose
            # size follows the input.
            self.dynamic_allocations += 1
            self._note(node.lineno, f'调用 {name}() 建立随输入增长的容器', 'ALLOCATION')
        if name in ('sort', 'sorted', 'heapify', 'heappush', 'heappop', 'nlargest', 'nsmallest'):
            self.sorts += 1
            if self.current_function is not None:
                self.function_sorts.add(self.current_function)
            poly, log = self.stack.snapshot()
            self._record((poly + 1, max(log, 1)) if poly == 0 else (poly, log + 1))
        elif name in _WHOLE_CONTAINER_CALLS and self.stack.snapshot() == (0, 0):
            # One top-level sweep over the input. Inside a loop this would be
            # n times that loop, which the loop rule already covers.
            self._record((1, 0))
        if name and self.current_function and name == self.current_function:
            self.call_counts[name] = self.call_counts.get(name, 0) + 1
        for child in ast.iter_child_nodes(node):
            self.visit(child)

    def _visit_comprehension(self, node) -> None:
        generators = len(node.generators)
        for _ in range(generators):
            self.stack.push('n')
        if self.current_function is not None:
            self.function_loops.add(self.current_function)
        self.max_loop_depth = max(self.max_loop_depth, self.stack.poly + self.stack.log)
        self._record(self.stack.snapshot())
        self.dynamic_allocations += 1
        # ``[[0] * m for _ in range(n)]`` builds a matrix: the element is itself
        # a list, so the container holds n rows of m cells.
        element_node = getattr(node, 'elt', None)
        if isinstance(element_node, (ast.List, ast.ListComp)) or (
                isinstance(element_node, ast.BinOp) and isinstance(element_node.op, ast.Mult)
                and isinstance(element_node.left, ast.List)):
            self.matrix_allocations += 1
            self._note(node.lineno, '推导式构造二维表', 'MATRIX')
        self._note(node.lineno, f'推导式：{generators} 层迭代并分配新容器', 'ALLOCATION')
        for generator in node.generators:
            for child in ast.iter_child_nodes(generator):
                self.visit(child)
        for attribute in ('elt', 'key', 'value'):
            child = getattr(node, attribute, None)
            if child is not None:
                self.visit(child)
        for _ in range(generators):
            self.stack.pop('n')

    visit_ListComp = _visit_comprehension
    visit_SetComp = _visit_comprehension
    visit_DictComp = _visit_comprehension
    visit_GeneratorExp = _visit_comprehension

    def visit_List(self, node: ast.List) -> None:
        if node.elts:
            self.dynamic_allocations += 1
            if all(isinstance(element, ast.List) for element in node.elts):
                self.matrix_allocations += 1
                self._note(node.lineno, '构造二维表', 'MATRIX')
        for child in ast.iter_child_nodes(node):
            self.visit(child)

    def visit_BinOp(self, node: ast.BinOp) -> None:
        # ``[0] * n`` allocates n cells; ``[[0]*m] * n`` allocates a matrix.
        if isinstance(node.op, ast.Mult) and isinstance(node.left, ast.List):
            self.dynamic_allocations += 1
            if node.left.elts and all(isinstance(element, ast.List) for element in node.left.elts):
                self.matrix_allocations += 1
                self._note(node.lineno, '按规模构造二维表', 'MATRIX')
        for child in ast.iter_child_nodes(node):
            self.visit(child)


def _call_name(func: ast.AST) -> str:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ''


def _halving_expression(value: ast.AST) -> bool:
    for node in ast.walk(value):
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.FloorDiv, ast.RShift)):
            return True
    return False


def _loop_halves(node: ast.While) -> bool:
    """True when the loop's own bound shrinks geometrically inside the body.

    Two shapes are accepted: a tested variable updated with a halving
    expression, and the canonical binary-search update where a tested bound is
    reassigned from a variable that was itself computed with ``// 2``.
    """
    tested = {child.id for child in ast.walk(node.test) if isinstance(child, ast.Name)}
    if not tested:
        return False
    midpoint_names: set[str] = set()
    for statement in node.body:
        for child in ast.walk(statement):
            if isinstance(child, ast.Assign):
                for target in child.targets:
                    if isinstance(target, ast.Name) and _halving_expression(child.value):
                        midpoint_names.add(target.id)
    for statement in node.body:
        for child in ast.walk(statement):
            if isinstance(child, ast.Assign):
                for target in child.targets:
                    if not isinstance(target, ast.Name) or target.id not in tested:
                        continue
                    if _halving_expression(child.value):
                        return True
                    # ``hi = mid`` / ``lo = mid + 1`` where mid = (lo+hi)//2.
                    if _references_any(child.value, midpoint_names):
                        return True
            if isinstance(child, ast.AugAssign) and isinstance(child.target, ast.Name) \
                    and child.target.id in tested \
                    and isinstance(child.op, (ast.FloorDiv, ast.RShift)):
                return True
    return False


def _references_any(value: ast.AST, names: set[str]) -> bool:
    if not names:
        return False
    return any(isinstance(node, ast.Name) and node.id in names for node in ast.walk(value))


def _recursion_shape(body: ast.AST, name: str) -> tuple[str, int]:
    """Classify how a recursive call shrinks its argument.

    Returns ``(kind, calls)`` where kind is HALVED (n/2), DECREMENT (n-1), ANGLE
    (a constant, as in Hanoi) or UNKNOWN, and calls is the number of recursive
    calls found in the body.
    """
    kinds: list[str] = []
    for node in ast.walk(body):
        if not isinstance(node, ast.Call):
            continue
        if not (isinstance(node.func, ast.Name) and node.func.id == name):
            continue
        if not node.args:
            kinds.append('UNKNOWN')
            continue
        argument = node.args[0]
        if isinstance(argument, ast.Subscript) and isinstance(argument.slice, ast.Slice):
            kinds.append('HALVED')
        elif _halving_expression(argument):
            kinds.append('HALVED')
        elif isinstance(argument, ast.BinOp) and isinstance(argument.op, ast.Sub):
            kinds.append('DECREMENT')
        elif _is_constant(argument):
            kinds.append('ANGLE')
        else:
            kinds.append('UNKNOWN')
    if not kinds:
        return 'UNKNOWN', 0
    calls = len(kinds)
    if all(kind == 'HALVED' for kind in kinds):
        return 'HALVED', calls
    if all(kind == 'DECREMENT' for kind in kinds):
        return 'DECREMENT', calls
    if all(kind == 'ANGLE' for kind in kinds):
        return 'ANGLE', calls
    if 'HALVED' in kinds:
        return 'HALVED', calls
    if 'DECREMENT' in kinds:
        return 'DECREMENT', calls
    return 'UNKNOWN', calls


def _is_constant(node: ast.AST) -> bool:
    if isinstance(node, ast.Constant):
        return True
    if isinstance(node, ast.BinOp):
        return _is_constant(node.left) and _is_constant(node.right)
    return False


def analyze_python(source: str) -> StaticAnalysis:
    try:
        tree = ast.parse(source)
    except SyntaxError as error:
        return StaticAnalysis(
            language_family='python', time_class='UNKNOWN', space_class='UNKNOWN',
            confidence='LOW', evidence=[{'line': error.lineno or 0,
                                         'reason': '源码无法解析', 'kind': 'PARSE_ERROR'}],
            notes=['静态分析无法解析该源码，结论只来自实测'])
    visitor = _PythonVisitor()
    for statement in tree.body:
        visitor.visit(statement)
    evidence = list(visitor.evidence)
    loop_class = _classify(visitor.best_shape)
    if visitor.max_loop_depth:
        evidence.append({'line': visitor.max_loop_lines[0] if visitor.max_loop_lines else 0,
                         'reason': f'最深层循环嵌套 {visitor.max_loop_depth} 层',
                         'kind': 'LOOP_DEPTH'})

    # Recursion shape, evaluated per recursive function.
    recursion_class = 'O(1)'
    recursion_kind = 'NONE'
    for name, calls in visitor.call_counts.items():
        body = visitor.function_bodies.get(name)
        if body is None:
            continue
        shape, call_count = _recursion_shape(body, name)
        recursion_kind = shape
        per_call = _classify(visitor.best_shape) if name in visitor.function_loops else 'O(1)'
        if call_count >= 3:
            recursion_class = 'O(2^n)'
        elif call_count == 2:
            if shape == 'HALVED':
                recursion_class = 'O(n log n)' if per_call == 'O(n)' else 'O(n)'
                evidence.append({'line': 0, 'reason': '双路折半递归，每层线性合并（分治）',
                                 'kind': 'DIVIDE_CONQUER'})
            elif shape == 'DECREMENT':
                recursion_class = 'O(2^n)'
                evidence.append({'line': 0, 'reason': '双路递减递归，分支数指数增长',
                                 'kind': 'EXPONENTIAL_RECURSION'})
            else:
                recursion_class = 'O(2^n)'
                evidence.append({'line': 0, 'reason': '双路常数递归，调用次数指数增长',
                                 'kind': 'EXPONENTIAL_RECURSION'})
        elif call_count == 1:
            if shape == 'HALVED':
                recursion_class = 'O(log n)'
            elif shape == 'DECREMENT':
                recursion_class = 'O(n^2)' if per_call in ('O(n)', 'O(n log n)') else 'O(n)'
                evidence.append({'line': 0, 'reason': '单路递减递归，层数为 n',
                                 'kind': 'LINEAR_RECURSION'})
            else:
                recursion_class = 'O(n)'
        break

    # Compare final class names: O(2^n) cannot be expressed as a (poly, log) pair.
    time_class = loop_class if CLASS_RANK[loop_class] >= CLASS_RANK[recursion_class] else recursion_class

    # Space: containers growing with the input, recursion depth, matrices.
    space_class = 'O(1)'
    if visitor.dynamic_allocations:
        space_class = 'O(n)'
        evidence.append({'line': 0, 'reason': '存在随输入规模增长的容器', 'kind': 'SPACE'})
    if visitor.matrix_allocations:
        space_class = 'O(n^2)'
    if recursion_kind in ('HALVED', 'DECREMENT', 'ANGLE') and recursion_class != 'O(1)':
        # Halving recursion alone needs O(log n) stack frames; a linear merge in
        # each frame (divide and conquer) allocates O(n) at a time.
        stack_space = 'O(log n)'
        if recursion_kind == 'HALVED' and loop_class in ('O(n)', 'O(n log n)'):
            stack_space = 'O(n)'
        space_class = _greater(space_class, stack_space)
        evidence.append({'line': 0, 'reason': '递归深度随规模增长，占用调用栈', 'kind': 'STACK'})

    confidence = 'MEDIUM'
    if visitor.best_shape == (0, 0) and not visitor.call_counts and not visitor.dynamic_allocations:
        confidence = 'HIGH' if not visitor.sorts else 'MEDIUM'
    elif any(kind in ('LOOP_DEPTH', 'DIVIDE_CONQUER', 'EXPONENTIAL_RECURSION', 'LINEAR_RECURSION',
                      'HALVING') for kind in (item['kind'] for item in evidence)):
        confidence = 'HIGH'
    notes = []
    if visitor.sorts:
        notes.append('检测到排序调用；排序为 O(n log n)，不改变更高阶项的判断')
    if visitor.reductions:
        notes.append('检测到折半收缩：二分、分治或快速幂类结构')
    return StaticAnalysis(
        language_family='python', time_class=time_class, space_class=space_class,
        confidence=confidence, evidence=evidence, loop_depth=visitor.max_loop_depth,
        max_loop_lines=visitor.max_loop_lines, recursive=bool(visitor.call_counts),
        recursion_kind=recursion_kind, logarithmic_loops=visitor.reductions,
        sorts=visitor.sorts, dynamic_allocations=visitor.dynamic_allocations,
        matrix_allocations=visitor.matrix_allocations, notes=notes)


def _raise_log_factor(name: str) -> str:
    mapping = {'O(1)': 'O(log n)', 'O(log n)': 'O(log n)', 'O(n)': 'O(n log n)',
               'O(n log n)': 'O(n log n)', 'O(n^2)': 'O(n^2 log n)',
               'O(n^2 log n)': 'O(n^2 log n)', 'O(n^3)': 'O(n^3)', 'O(2^n)': 'O(2^n)'}
    return mapping.get(name, name)


_FOR_KEYWORD = re.compile(r'\b(for|while|do)\b')
_HALVING = re.compile(r'>>=?\s*1\b|/=\s*2\b|\*\s*=\s*2\b|/\s*2\b')
_CALL = re.compile(r'\b([A-Za-z_][A-Za-z_0-9]*)\s*\(')
_ARRAY = re.compile(r'\[\s*[A-Za-z_][A-Za-z_0-9]*\s*\]\s*\[\s*[A-Za-z_][A-Za-z_0-9]*\s*\]')
_COMPARISON = re.compile(r'[<>]=?|!=|==')


def analyze_lexical(source: str, language_family: str) -> StaticAnalysis:
    """Structural estimate for C/C++/Java without a parser.

    Braces give block nesting; every loop keyword attaching to the same block
    increases that block's loop depth, so ``for(...) for(...) { }`` counts as two
    nested loops even without inner braces. The result is explicitly
    lexical-only: it can count loop nesting, but it cannot resolve calls,
    templates or early exits. Confidence therefore stays LOW, the report says
    lexical_only, and the empirical growth measurement outranks it.
    """
    text = _strip_comments(source)
    depth = 0
    paren_depth = 0
    loop_stack: list[int] = []
    max_loop_depth = 0
    loops = 0
    pending = 0
    evidence: list[dict] = []
    line = 1
    index = 0
    length = len(text)
    while index < length:
        char = text[index]
        if char == '\n':
            line += 1
            index += 1
            continue
        if char == '(':
            paren_depth += 1
            index += 1
            continue
        if char == ')':
            paren_depth = max(0, paren_depth - 1)
            index += 1
            continue
        match = _FOR_KEYWORD.match(text, index)
        if match and (index == 0 or not (text[index - 1].isalnum() or text[index - 1] == '_')):
            loops += 1
            pending += 1
            max_loop_depth = max(max_loop_depth, len(loop_stack) + pending)
            index = match.end()
            continue
        if char == '{':
            depth += 1
            for _ in range(pending):
                loop_stack.append(depth)
            pending = 0
        elif char == '}':
            if loop_stack and loop_stack[-1] == depth:
                loop_stack.pop()
            depth = max(0, depth - 1)
            if depth == 0:
                pending = 0
        elif char == ';' and pending and paren_depth == 0:
            # A brace-free loop body ends at the statement terminator. A
            # semicolon inside the ``for(...)`` header must not count.
            pending = 0
        index += 1
    if pending:
        max_loop_depth = max(max_loop_depth, len(loop_stack) + pending)
    body_text = ' '.join(text.split())
    halving = 1 if _HALVING.search(body_text) else 0
    if halving:
        evidence.append({'line': 0, 'reason': '出现折半更新，可能为对数循环', 'kind': 'LOG_FACTOR'})
    if max_loop_depth:
        evidence.append({'line': 0, 'reason': f'词法统计到最多 {max_loop_depth} 层循环',
                         'kind': 'LOOP_DEPTH'})
    base = {0: 'O(1)', 1: 'O(n)', 2: 'O(n^2)', 3: 'O(n^3)'}[min(max_loop_depth, 3)]
    if halving and max_loop_depth in (0, 1):
        base = 'O(log n)' if max_loop_depth == 0 else 'O(n log n)'
    elif halving and max_loop_depth >= 2:
        evidence.append({'line': 0,
                         'reason': '折半更新可能压低其中一层循环，词法分析无法确认，按上界给出',
                         'kind': 'UPPER_BOUND'})
    self_call = _self_calls(text)
    if self_call:
        evidence.append({'line': 0, 'reason': f'函数 {self_call} 直接调用自身，可能是递归',
                         'kind': 'RECURSION'})
        base = _greater(base, 'O(n)')
    evidence.append({'line': 0, 'reason': '结构化语言只做词法结构估计，未建立语法树',
                     'kind': 'LEXICAL_ONLY'})
    space_class = 'O(n^2)' if _ARRAY.search(body_text) else (
        'O(n)' if ('new ' in body_text or 'malloc' in body_text or 'vector' in body_text) else 'O(1)')
    return StaticAnalysis(
        language_family=language_family, time_class=base, space_class=space_class,
        confidence='LOW', evidence=evidence, loop_depth=min(max_loop_depth, 3),
        recursive=bool(self_call), recursion_kind='LEXICAL' if self_call else None,
        logarithmic_loops=halving,
        notes=['结构化语言没有语法树分析，结论为词法上界，置信度低，仅作参考'])


def _self_calls(text: str) -> str | None:
    """Return the first function name that calls itself, if any."""
    for match in re.finditer(r'\b([A-Za-z_][A-Za-z_0-9]*)\s*\([^;{}]*\)\s*\{', text):
        name = match.group(1)
        body_start = match.end() - 1
        depth = 0
        cursor = body_start
        while cursor < len(text):
            if text[cursor] == '{':
                depth += 1
            elif text[cursor] == '}':
                depth -= 1
                if depth == 0:
                    break
            cursor += 1
        body = text[body_start:cursor]
        if re.search(r'\b' + re.escape(name) + r'\s*\(', body):
            return name
    return None


def _strip_comments(source: str) -> str:
    text = re.sub(r'/\*.*?\*/', ' ', source, flags=re.S)
    return re.sub(r'//[^\n]*', ' ', text)


def analyze_static(source: str, language: str | None) -> StaticAnalysis:
    family = language_family(language)
    if family == 'python':
        return analyze_python(source)
    if family == 'c-like':
        return analyze_lexical(source, family)
    return StaticAnalysis(language_family=family or 'unknown', time_class='UNKNOWN',
                          space_class='UNKNOWN', confidence='LOW',
                          notes=['不支持的语言，无法静态分析'])


# -------------------------------------------------------------------- dynamic


@dataclass
class Measurement:
    n: int
    wall_ms: float
    adjusted_ms: float
    peak_rss_kib: int | None
    verdict: str
    repeats: int = 1

    def to_payload(self) -> dict:
        return {'n': self.n, 'wall_ms': round(self.wall_ms, 3),
                'adjusted_ms': round(self.adjusted_ms, 3),
                'peak_rss_kib': self.peak_rss_kib, 'verdict': self.verdict,
                'repeats': self.repeats}


@dataclass
class GrowthFit:
    fitted_class: str
    r2: float
    exponent: float
    coefficient: float
    used_points: list[dict]
    discarded: list[dict]
    confidence: str
    offset_ms: float = 0.0
    floor_ms: float = 0.0
    notes: list[str] = field(default_factory=list)
    dominant_class: str | None = None

    def to_payload(self) -> dict:
        return {'fitted_class': self.fitted_class, 'r2': round(self.r2, 6),
                'exponent': round(self.exponent, 4), 'coefficient': self.coefficient,
                'offset_ms': self.offset_ms, 'floor_ms': self.floor_ms,
                'used_points': self.used_points, 'discarded': self.discarded,
                'confidence': self.confidence, 'notes': self.notes,
                'dominant_class': self.dominant_class}


def _fit_with_offset(values: list[float], times: list[float]) -> tuple[float, float] | None:
    """Least squares for ``t = a*v + b`` with ``a > 0`` and ``b >= 0``.

    A plain two-parameter regression can return a negative ``b`` on a noisy
    ladder; that is not physically meaningful (time cannot be negative at
    ``n = 0``), so the result is clamped and the slope recomputed.
    """
    count = len(values)
    if count < 2:
        return None
    mean_v = sum(values) / count
    mean_t = sum(times) / count
    denominator = sum((v - mean_v) ** 2 for v in values)
    if denominator <= 1e-18:
        # Constant basis function (O(1)): the only free parameter is the mean,
        # which is a valid fit rather than a failure.
        return (mean_t, 0.0) if mean_t > 0 else None
    a = sum((v - mean_v) * (t - mean_t) for v, t in zip(values, times)) / denominator
    b = mean_t - a * mean_v
    if a <= 0:
        return None
    if b < 0:
        b = 0.0
        squared = sum(v * v for v in values)
        if squared <= 0:
            return None
        a = sum(v * t for v, t in zip(values, times)) / squared
        if a <= 0:
            return None
    return a, b


# Expected log-log slope of each class. The slope is measured independently of
# the fit, so it acts as a physical filter on which classes are even admissible.
_EXPECTED_EXPONENT = {'O(1)': 0.0, 'O(log n)': 0.1, 'O(n)': 1.0, 'O(n log n)': 1.15,
                      'O(n^2)': 2.0, 'O(n^2 log n)': 2.15, 'O(n^3)': 3.0, 'O(2^n)': 4.0}
EXPONENT_TOLERANCE = 0.7


def observed_exponent(points: list[Measurement]) -> float | None:
    """Slope of log(time) against log(n), regressed without an intercept.

    Only points above the start-up floor are used: a sub-millisecond rung is
    dominated by process launch and would bias the slope towards zero.
    """
    usable = [point for point in points if point.n > 1 and point.wall_ms > 0]
    if len(usable) < 2:
        return None
    xs = [math.log(point.n) for point in usable]
    ys = [math.log(point.wall_ms) for point in usable]
    mean_x = sum(xs) / len(xs)
    mean_y = sum(ys) / len(ys)
    denominator = sum((x - mean_x) ** 2 for x in xs)
    if denominator <= 0:
        return None
    return sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys)) / denominator


@dataclass
class DynamicConclusion:
    """What the measurement alone can and cannot say.

    ``measured_class`` is the growth class of the *total* run time. Total time is
    algorithm work plus input parsing, and the class of a sum is the larger of
    the two classes. The reference reader measures the parsing part alone, so:

    * ``measured > io``  -> the algorithm must grow at ``measured``: informative.
    * ``measured == io`` -> the algorithm is at most ``io``: the measurement only
      gives an upper bound and cannot exclude a cheaper algorithm.
    * ``measured < io``  -> impossible in theory; treat as uninformative.
    """

    measured_class: str
    io_class: str
    informative: bool
    r2: float
    exponent: float | None
    confidence: str
    floor_ms: float
    fit: GrowthFit
    reference_fit: GrowthFit | None
    accounting: list[dict]

    def to_payload(self) -> dict:
        return {
            'measured_class': self.measured_class,
            'io_class': self.io_class,
            'informative': self.informative,
            'r2': round(self.r2, 6),
            'exponent': None if self.exponent is None else round(self.exponent, 4),
            'confidence': self.confidence,
            'floor_ms': self.floor_ms,
            'fit': self.fit.to_payload(),
            'reference_fit': self.reference_fit.to_payload() if self.reference_fit else None,
            'accounting': self.accounting,
        }


def classify_growth(measurements: list[Measurement],
                    reference_ms: dict[int, float] | None = None) -> DynamicConclusion:
    """Fit the measured ladder and decide whether the result is informative.

    ``reference_ms`` maps ``n`` to the time of a pure input-reading program on
    the same generated input. If it is missing, the reference class is unknown
    and the measured class is accepted as-is (with a note in the report).
    """
    reference_ms = reference_ms or {}
    ok = [item for item in measurements if item.verdict == 'OK' and item.wall_ms > 0]
    accounting: list[dict] = []
    for item in measurements:
        reference = reference_ms.get(item.n)
        accounting.append({
            'n': item.n, 'wall_ms': round(item.wall_ms, 3) if item.wall_ms else 0.0,
            'reference_ms': None if reference is None else round(reference, 3),
            'io_ratio': (round(item.wall_ms / reference, 2)
                         if reference and item.wall_ms else None),
            'peak_rss_kib': item.peak_rss_kib, 'verdict': item.verdict,
        })
    floor = min((item.wall_ms for item in ok), default=0.0)
    fit = fit_growth(ok, floor_ms=floor)
    reference_points = [Measurement(n=n, wall_ms=value, adjusted_ms=value, peak_rss_kib=None,
                                    verdict='OK')
                        for n, value in sorted(reference_ms.items()) if value and value > 0]
    reference_fit = fit_growth(reference_points, minimum_points=3) if len(reference_points) >= 3 else None
    io_class = 'UNKNOWN'
    if reference_fit is not None and reference_fit.confidence != 'LOW':
        io_class = reference_fit.fitted_class
    informative = True
    if io_class != 'UNKNOWN' and fit.fitted_class != 'UNKNOWN':
        informative = CLASS_RANK[fit.fitted_class] > CLASS_RANK[io_class]
    return DynamicConclusion(
        measured_class=fit.fitted_class, io_class=io_class, informative=informative,
        r2=fit.r2, exponent=fit.exponent, confidence=fit.confidence,
        floor_ms=round(floor, 3), fit=fit, reference_fit=reference_fit,
        accounting=accounting)


def _fit_with_offset(values: list[float], times: list[float]) -> tuple[float, float] | None:
    """Least squares for ``t = a*v + b`` with ``a > 0`` and ``b >= 0``.

    A plain two-parameter regression can return a negative ``b`` on a noisy
    ladder; that is not physically meaningful (time cannot be negative at
    ``n = 0``), so the result is clamped and the slope recomputed.
    """
    count = len(values)
    if count < 2:
        return None
    mean_v = sum(values) / count
    mean_t = sum(times) / count
    denominator = sum((v - mean_v) ** 2 for v in values)
    if denominator <= 1e-18:
        # Constant basis function (O(1)): the only free parameter is the mean,
        # which is a valid fit rather than a failure.
        return (mean_t, 0.0) if mean_t > 0 else None
    a = sum((v - mean_v) * (t - mean_t) for v, t in zip(values, times)) / denominator
    b = mean_t - a * mean_v
    if a <= 0:
        return None
    if b < 0:
        b = 0.0
        squared = sum(v * v for v in values)
        if squared <= 0:
            return None
        a = sum(v * t for v, t in zip(values, times)) / squared
        if a <= 0:
            return None
    return a, b


# Expected log-log slope of each class. The slope is measured independently of
# the fit, so it acts as a physical filter on which classes are even admissible.
_EXPECTED_EXPONENT = {'O(1)': 0.0, 'O(log n)': 0.1, 'O(n)': 1.0, 'O(n log n)': 1.15,
                      'O(n^2)': 2.0, 'O(n^2 log n)': 2.15, 'O(n^3)': 3.0, 'O(2^n)': 4.0}
EXPONENT_TOLERANCE = 0.7


def observed_exponent(points: list[Measurement]) -> float | None:
    """Slope of log(time) against log(n), regressed without an intercept.

    Only points above the start-up floor are used: a sub-millisecond rung is
    dominated by process launch and would bias the slope towards zero.
    """
    usable = [point for point in points if point.n > 1 and point.wall_ms > 0]
    if len(usable) < 2:
        return None
    xs = [math.log(point.n) for point in usable]
    ys = [math.log(point.wall_ms) for point in usable]
    mean_x = sum(xs) / len(xs)
    mean_y = sum(ys) / len(ys)
    denominator = sum((x - mean_x) ** 2 for x in xs)
    if denominator <= 0:
        return None
    return sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys)) / denominator


def attribute_growth(measurements: list[Measurement], reference_ms: dict[int, float] | None = None,
                     *, minimum_ratio: float = 1.0) -> tuple[list[Measurement], list[dict]]:
    """Split each rung's time into input parsing and algorithm work.

    ``algorithm_ms = measured - reference_reader_ms``, floored at zero. The
    reference reader is a program that reads the same generated input and does
    nothing else, so whatever it does not explain is the submission's own work.
    Rungs where the submission is not at least ``minimum_ratio`` times the
    reader are still reported but marked ``IO_DOMINATED`` and excluded from the
    fit: their growth belongs to parsing, not to the algorithm.

    Returns ``(algorithm_points, accounting)`` where ``accounting`` is the full
    per-rung table for the report.
    """
    reference_ms = reference_ms or {}
    points: list[Measurement] = []
    accounting: list[dict] = []
    for item in measurements:
        reference = reference_ms.get(item.n)
        row = {'n': item.n, 'wall_ms': round(item.wall_ms, 3),
               'reference_ms': None if reference is None else round(reference, 3),
               'verdict': item.verdict}
        if item.verdict != 'OK' or reference is None:
            row['algorithm_ms'] = None
            row['io_ratio'] = None
            accounting.append(row)
            continue
        algorithm_ms = max(0.0, item.wall_ms - reference)
        ratio = item.wall_ms / reference if reference > 0 else None
        row['algorithm_ms'] = round(algorithm_ms, 3)
        row['io_ratio'] = None if ratio is None else round(ratio, 2)
        accounting.append(row)
        if ratio is not None and ratio < minimum_ratio:
            continue
        points.append(Measurement(n=item.n, wall_ms=item.wall_ms, adjusted_ms=algorithm_ms,
                                  peak_rss_kib=item.peak_rss_kib, verdict='OK',
                                  repeats=item.repeats))
    return points, accounting


def fit_growth(measurements: Iterable[Measurement], *, minimum_points: int = 3,
               floor_ms: float | None = None) -> GrowthFit:
    """Fit ``t = a*f(n) + b`` and pick the complexity class.

    Two independent filters decide the class, because either alone is fragile on
    a short ladder:

    1. R^2 of the affine fit over every completed rung, with ``b`` allowed to be
       positive: process start-up is a real constant and ignoring it makes fast
       programs look flat.
    2. The log-log slope, which must land within :data:`EXPONENT_TOLERANCE` of
       the class's expected exponent. This rejects a steep class that happens to
       fit a single noisy top rung.

    ``floor_ms`` marks the measured start-up constant; rungs at or below it are
    reported but excluded from the slope, and a ladder where every rung sits on
    the floor is reported as ``O(1)``-or-below with LOW confidence rather than
    being given an invented growth class.
    """
    all_points = [item for item in measurements if item.verdict == 'OK' and item.wall_ms > 0]
    discarded = [item.to_payload() for item in measurements if item.verdict != 'OK']
    if floor_ms is None:
        floor_ms = min((point.wall_ms for point in all_points), default=0.0)
    elevated = [point for point in all_points if point.wall_ms > floor_ms * 1.35]
    if len(all_points) < minimum_points:
        return GrowthFit('UNKNOWN', 0.0, 0.0, 0.0, [p.to_payload() for p in all_points],
                         discarded, 'LOW')
    sizes = [p.n for p in all_points]
    times = [p.wall_ms for p in all_points]
    mean_t = sum(times) / len(times)
    total = sum((t - mean_t) ** 2 for t in times)
    slope = observed_exponent(elevated if len(elevated) >= 3 else all_points)

    candidates: list[tuple[str, float, float, float]] = []
    for name in TIME_CLASSES:
        values = [GROWTH_FUNCTIONS[name](n) for n in sizes]
        coefficients = _fit_with_offset(values, times)
        if coefficients is None:
            continue
        a, b = coefficients
        residuals = [t - (a * v + b) for t, v in zip(times, values)]
        r2 = 1.0 if total <= 1e-12 else 1 - sum(r * r for r in residuals) / total
        candidates.append((name, r2, a, b))
    if not candidates:
        return GrowthFit('UNKNOWN', 0.0, slope or 0.0, 0.0, [p.to_payload() for p in all_points],
                         discarded, 'LOW')
    admissible = [row for row in candidates
                  if slope is None or abs(_EXPECTED_EXPONENT[row[0]] - slope) <= EXPONENT_TOLERANCE]
    if not admissible:
        # Nothing fits the observed slope: report the nearest class but never
        # claim confidence in it.
        nearest = min(candidates, key=lambda row: abs(_EXPECTED_EXPONENT[row[0]] - (slope or 0.0)))
        result = GrowthFit(nearest[0], max(0.0, min(1.0, nearest[1])), slope or 0.0,
                           round(nearest[2], 8), [p.to_payload() for p in all_points],
                           discarded, 'LOW')
        result.offset_ms = round(nearest[3], 3)
        result.notes = ['增长斜率与所有候选类别都不吻合，仅给出最接近的一个']
        return result
    best = admissible[0]
    for row in admissible[1:]:
        if row[1] > best[1] + 0.005:
            best = row
        elif abs(row[1] - best[1]) <= 0.005 and CLASS_RANK[row[0]] < CLASS_RANK[best[0]]:
            best = row
    name, r2, a, b = best
    confidence = 'LOW'
    if r2 >= 0.985 and len(all_points) >= 4 and len(elevated) >= 3:
        confidence = 'HIGH'
    elif r2 >= 0.90 and len(all_points) >= 3:
        confidence = 'MEDIUM'
    if slope is not None and name == 'O(1)' and len(elevated) >= 3 and slope > 0.5:
        confidence = 'LOW'
    result = GrowthFit(name, max(0.0, min(1.0, r2)), slope or 0.0, round(a, 8),
                       [p.to_payload() for p in all_points], discarded, confidence)
    result.offset_ms = round(b, 3)
    result.floor_ms = round(floor_ms, 3)
    result.notes = []
    if len(elevated) < 3:
        result.notes.append('多数档位仍在启动开销附近，增长信号偏弱')
    return result


# -------------------------------------------------------------------- combine


def combine(static: StaticAnalysis, dynamic: DynamicConclusion,
            memory: dict | None = None) -> dict:
    """Merge both estimators into the verdict shown to students.

    Rules, in order:

    1. Measurement wins when it is informative (its class is above the pure
       input-parsing class) and its confidence is not LOW.
    2. Otherwise the static structure is the primary source, because a
       measurement that never exceeds input parsing cannot separate a cheaper
       algorithm from a linear one.
    3. Disagreement and every limitation are written into the report instead of
       being averaged away.
    """
    limitations: list[str] = []
    fit = dynamic.fit
    dynamic_usable = (dynamic.informative and fit.fitted_class != 'UNKNOWN'
                      and fit.confidence in ('MEDIUM', 'HIGH'))
    if dynamic_usable:
        time_class = fit.fitted_class
        time_source = 'DYNAMIC'
        time_confidence = fit.confidence
    else:
        time_class = static.time_class
        time_source = 'STATIC'
        time_confidence = static.confidence
        if dynamic.measured_class != 'UNKNOWN':
            if not dynamic.informative:
                limitations.append(
                    f'实测总时间增长约为 {dynamic.measured_class}，与纯输入读取（{dynamic.io_class}）'
                    '同阶或更低；被测程序没有明显超过读取输入的开销，因此实测只能给出上界，'
                    f'时间结论以代码结构分析（{static.time_class}）为准')
            else:
                limitations.append(
                    f'实测增长 {dynamic.measured_class} 的置信度偏低（R²={dynamic.r2:.3f}），'
                    f'未超过结构分析 {static.time_class} 的证据强度')
    agreement = None
    if static.time_class != 'UNKNOWN' and dynamic.measured_class != 'UNKNOWN':
        agreement = static.time_class == dynamic.measured_class
        if not agreement and dynamic.informative and dynamic_usable:
            limitations.append(
                f'结构分析给出 {static.time_class}，实测增长为 {dynamic.measured_class}；'
                '以实测为准，但两者不一致说明结论只能作为参考')
    if fit.discarded:
        limitations.append(f'{len(fit.discarded)} 个档位未能完成测量（超时或运行错误），已从拟合中剔除')
    if len(fit.used_points) < 4:
        limitations.append('有效测量档位少于 4 个，增长拟合容易受常数开销影响')

    space_class = static.space_class
    space_confidence = static.confidence
    if memory:
        growth = memory.get('growth')
        dynamic_space = memory.get('class')
        if dynamic_space and growth is not None and growth > 1.5:
            if CLASS_RANK.get(dynamic_space, 0) > CLASS_RANK.get(space_class, 0):
                space_class = dynamic_space
                space_confidence = 'MEDIUM'
                limitations.append('实测内存随规模增长，空间结论取静态与实测中较高的一项')

    summary = {
        'time': {'class': time_class, 'confidence': time_confidence, 'source': time_source,
                 'static_class': static.time_class, 'measured_class': dynamic.measured_class,
                 'agreement': agreement},
        'space': {'class': space_class, 'confidence': space_confidence, 'source': 'STATIC',
                  'static_class': static.space_class},
        'limitations': limitations,
    }
    if fit.fitted_class != 'UNKNOWN':
        summary['time']['r2'] = round(fit.r2, 4)
        summary['time']['exponent'] = round(fit.exponent, 3)
        summary['time']['offset_ms'] = fit.offset_ms
        summary['time']['coefficient'] = fit.coefficient
    return summary


def curve_points(time_class: str, coefficient: float, sizes: list[int],
                 offset_ms: float = 0.0, steps: int = 40) -> list[dict]:
    """Sampled fitted curve for the chart, using the same f(n) as the fit.

    The offset is included so the curve lines up with the measured points
    instead of starting at zero.
    """
    if time_class not in GROWTH_FUNCTIONS or not sizes:
        return []
    function = GROWTH_FUNCTIONS[time_class]
    low, high = min(sizes), max(sizes)
    if low <= 0:
        low = 1
    values = []
    for index in range(steps + 1):
        n = low + (high - low) * index / steps
        value = coefficient * function(n) + offset_ms
        values.append({'n': round(n, 3), 'time_ms': round(value, 4)})
    return values
