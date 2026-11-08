"""Deterministic peer-review algorithms. Pure functions over anonymous contracts.

Allocation minimizes convex reviewer workload, then repeated author/reviewer
history, then a seeded deterministic tie cost. Signals are review evidence only.
"""
from collections import Counter, defaultdict
from decimal import Decimal
import hashlib
import heapq
from statistics import median

from app.analysis.framework.contracts import AllocationOutput, SignalOutput


class Edge:
    __slots__ = ('to', 'reverse', 'capacity', 'cost')
    def __init__(self, to, reverse, capacity, cost):
        self.to, self.reverse, self.capacity, self.cost = to, reverse, capacity, cost


def allocation(data):
    answers = {a.answer_key: a.author_key for a in data.answers}
    reviewers = sorted(data.reviewers)
    if len(answers) != len(data.answers) or len(set(reviewers)) != len(reviewers):
        raise ValueError('Duplicate stable keys')
    if len(answers) > 300 or len(reviewers) > 300:
        raise ValueError('Allocation supports at most 300 answers/reviewers per snapshot')
    if not set(data.required_by_answer) <= answers.keys() or not set(data.prior_loads) <= set(reviewers):
        raise ValueError('Unknown requirement/load reference')
    if any(e.answer_key not in answers or e.reviewer_key not in reviewers
           for e in [*data.forbidden_edges, *data.existing_edges, *data.history]):
        raise ValueError('Allocation edge outside snapshot')
    demand = {a: data.required_by_answer.get(a, data.required_reviewers) for a in answers}
    total = sum(demand.values())
    if total > 2000:
        raise ValueError('Allocation supports at most 2000 new tasks')
    forbidden = {(e.answer_key, e.reviewer_key) for e in [*data.forbidden_edges, *data.existing_edges]}
    history = Counter((e.answer_key, e.reviewer_key) for e in data.history)
    prior = data.prior_loads or Counter(e.reviewer_key for e in data.existing_edges)
    loads = {r: 0 for r in reviewers}
    def infeasible(reasons):
        return AllocationOutput(feasible=False, edges=[], unmet_constraints=reasons, load_metrics=loads)
    if not answers:
        return infeasible(['NO_ANSWERS'])
    eligible = {a: [r for r in reviewers if r != answers[a] and (a, r) not in forbidden] for a in answers}
    missing = [f'{a}: needs {demand[a]}, eligible {len(eligible[a])}' for a in sorted(answers)
               if len(eligible[a]) < demand[a]]
    if missing:
        return infeasible(missing)
    a_nodes = {a: i + 1 for i, a in enumerate(sorted(answers))}
    r_nodes = {r: len(answers) + i + 1 for i, r in enumerate(reviewers)}
    sink = len(answers) + len(reviewers) + 1
    graph = [[] for _ in range(sink + 1)]
    def add(left, right, capacity, cost):
        edge = Edge(right, len(graph[right]), capacity, cost)
        reverse = Edge(left, len(graph[left]), 0, -cost)
        graph[left].append(edge); graph[right].append(reverse)
        return edge
    history_scale = total * 31 + 1
    fairness_scale = total * (max(history.values(), default=0) * history_scale + 31) + 1
    bindings = []
    for answer in sorted(answers):
        add(0, a_nodes[answer], demand[answer], 0)
        for reviewer in eligible[answer]:
            tie = int(hashlib.sha256(f'{data.seed}|{answer}|{reviewer}'.encode()).hexdigest()[:8], 16) % 31
            edge = add(a_nodes[answer], r_nodes[reviewer], 1,
                       history[(answer, reviewer)] * history_scale + tie)
            bindings.append((answer, reviewer, edge))
    for reviewer in reviewers:
        old = prior.get(reviewer, 0)
        capacity = min(len(answers), total)
        if data.max_tasks_per_reviewer is not None:
            capacity = min(capacity, max(0, data.max_tasks_per_reviewer - old))
        for slot in range(capacity):
            add(r_nodes[reviewer], sink, 1, (2 * (old + slot) + 1) * fairness_scale)
    potentials = [0] * len(graph)
    flow = 0
    infinity = 10 ** 60
    while flow < total:
        distance = [infinity] * len(graph); previous = [None] * len(graph)
        distance[0] = 0; queue = [(0, 0)]
        while queue:
            current, node = heapq.heappop(queue)
            if current != distance[node]:
                continue
            for index, edge in enumerate(graph[node]):
                if not edge.capacity:
                    continue
                value = current + edge.cost + potentials[node] - potentials[edge.to]
                if value < distance[edge.to]:
                    distance[edge.to] = value; previous[edge.to] = (node, index)
                    heapq.heappush(queue, (value, edge.to))
        if previous[sink] is None:
            return infeasible(['GLOBAL_CAPACITY_OR_FORBIDDEN_RELATIONS_INFEASIBLE'])
        for node, value in enumerate(distance):
            if value < infinity:
                potentials[node] += value
        node = sink
        while node:
            left, index = previous[node]; edge = graph[left][index]
            edge.capacity -= 1; graph[node][edge.reverse].capacity += 1; node = left
        flow += 1
    edges = []
    for answer, reviewer, edge in bindings:
        if edge.capacity == 0:
            edges.append({'answer_key': answer, 'reviewer_key': reviewer}); loads[reviewer] += 1
    return AllocationOutput(feasible=True, edges=edges, unmet_constraints=[], load_metrics=loads)


def _validate(data):
    keys = set()
    for e in [*data.evaluations, *data.history]:
        if e.evaluation_key in keys or e.score > data.rubric_max:
            raise ValueError('Duplicate evaluation or out-of-range score')
        keys.add(e.evaluation_key)


def _leave_one_out(data):
    """Independent median of other positive-weight reviewers; never compare against self."""
    by_answer = defaultdict(list)
    for e in data.evaluations:
        if e.weight > 0:
            by_answer[e.answer_key].append(e)
    comparable = []
    for target in data.evaluations:
        if target.weight <= 0:
            continue
        peers = [e.score / data.rubric_max for e in by_answer[target.answer_key]
                 if e.evaluation_key != target.evaluation_key and e.reviewer_key != target.reviewer_key]
        if len(peers) >= data.minimum_samples:
            comparable.append((target, target.score / data.rubric_max - median(peers)))
    return comparable


def deviation(data):
    _validate(data)
    rows = _leave_one_out(data)
    signals = [{'object_key': e.evaluation_key, 'kind': 'SINGLE_REVIEW_DEVIATION', 'value': abs(delta),
        'explanation': f'与其他评审者中位数偏离 {delta:+.6f}；阈值 {data.threshold}，仅作人工复核证据。'}
        for e, delta in rows if abs(delta) > data.threshold]
    return SignalOutput(signals=signals, sample_count=len(rows), missing_count=len(data.evaluations)-len(rows))


def reviewer_bias(data):
    _validate(data)
    baseline = {s.answer_key: s.normalized_score for s in data.history_baseline if s.normalized_score is not None}
    groups = defaultdict(list)
    for e in data.history:
        if e.weight > 0 and e.reviewer_key and e.answer_key in baseline:
            groups[e.reviewer_key].append((e.answer_key, e.score / data.rubric_max - baseline[e.answer_key]))
    signals = []; known = 0
    for reviewer, values in sorted(groups.items()):
        # At most one historical fact per answer contributes to an individual's estimate.
        per_answer = {key: value for key, value in values}
        if len(per_answer) < data.minimum_samples:
            continue
        known += 1; delta = median(per_answer.values())
        if abs(delta) > data.threshold:
            signals.append({'object_key': reviewer, 'kind': 'REVIEWER_HIGH_BIAS' if delta > 0 else 'REVIEWER_LOW_BIAS',
                'value': abs(delta), 'explanation': f'{len(per_answer)}份历史作品的固定基准残差中位数 {delta:+.6f}；不自动调整权重。'})
    current = {e.reviewer_key for e in data.evaluations if e.reviewer_key}
    return SignalOutput(signals=signals, sample_count=known, missing_count=max(0, len(current)-known))


def review_timing(data):
    known = [t for t in data.timings if t.elapsed_seconds is not None]
    if len(known) < data.minimum_samples:
        return SignalOutput(signals=[], sample_count=len(known), missing_count=len(data.timings)-len(known))
    threshold = min(data.short_seconds, median(t.elapsed_seconds for t in known) * data.relative_fraction)
    signals = [{'object_key': t.task_key, 'kind': 'SHORT_REVIEW_DURATION', 'value': t.elapsed_seconds,
        'explanation': f'服务端打开至提交耗时 {t.elapsed_seconds} 秒，小于本轮短时阈值 {threshold:.3f} 秒；不等同无效评价。'}
        for t in known if t.elapsed_seconds < threshold]
    return SignalOutput(signals=signals, sample_count=len(known), missing_count=len(data.timings)-len(known))


def relationship(data):
    _validate(data)
    rows = _leave_one_out(data)
    history_baseline = {s.answer_key:s.normalized_score for s in data.history_baseline
                        if s.normalized_score is not None and s.valid_count >= data.minimum_samples}
    rows += [(e,e.score/data.rubric_max-history_baseline[e.answer_key]) for e in data.history
             if e.weight>0 and e.answer_key in history_baseline]
    graph = defaultdict(set); evidence = Counter()
    for e, delta in rows:
        author = data.author_map.get(e.answer_key)
        if e.reviewer_key and author and e.reviewer_key != author and delta > data.threshold:
            graph[e.reviewer_key].add(author); evidence[(e.reviewer_key, author)] += 1
    # Tarjan SCC: reciprocal pairs and directed cycles are one auditable relation signal.
    nodes = set(graph) | {n for values in graph.values() for n in values}
    index = {}; low = {}; stack = []; active = set(); components = []
    def visit(node):
        index[node] = low[node] = len(index); stack.append(node); active.add(node)
        for other in sorted(graph[node]):
            if other not in index:
                visit(other); low[node] = min(low[node], low[other])
            elif other in active:
                low[node] = min(low[node], index[other])
        if low[node] == index[node]:
            group = []
            while True:
                other = stack.pop(); active.remove(other); group.append(other)
                if other == node:
                    break
            components.append(group)
    for node in sorted(nodes):
        if node not in index:
            visit(node)
    signals = []
    current_reviewers = {e.reviewer_key for e in data.evaluations if e.reviewer_key}
    for group in components:
        if len(group) < 2:
            continue
        members = set(group); arcs = sum(b in members for a in members for b in graph[a])
        count = sum(v for (a, b), v in evidence.items() if a in members and b in members)
        if count < data.minimum_samples:
            continue
        density = Decimal(arcs) / (len(group) * (len(group)-1))
        for reviewer in sorted(members & current_reviewers):
            signals.append({'object_key': reviewer, 'kind': 'RECIPROCAL_HIGH_SCORE_COMPONENT', 'value': density,
                'explanation': f'{len(group)}人高残差有向环组，{arcs}条关系、{count}条可比评价；密度{density:.6f}，仅供教师核查。'})
    return SignalOutput(signals=signals, sample_count=len(rows), missing_count=len(data.evaluations)+len(data.history)-len(rows))
