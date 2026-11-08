"""Deterministic, descriptive chapter performance. No I/O or inferred scores."""
from collections import defaultdict
from decimal import Decimal, localcontext

from ..framework.ability_contracts import (
    AbilityDiagnostics, AbilityEstimate, AbilityInputV2, AbilityMissing,
    AbilityOutputV2, AbilityTypeEstimate,
)


def analyze(data: AbilityInputV2) -> AbilityOutputV2:
    # Revalidate even models that a caller constructed without validation or mutated.
    data = AbilityInputV2.model_validate(data.model_dump())
    with localcontext() as ctx:
        ctx.prec = 28
        return _analyze(data)


def _analyze(data: AbilityInputV2) -> AbilityOutputV2:
    items = {item.item_key: item for item in data.items}
    grades = {}
    warnings = set()
    for grade in data.grades:
        key = grade.student_key, grade.item_key
        if key in grades:
            warnings.add(f'DUPLICATE_SCORE_DEDUPLICATED:{grade.student_key}:{grade.item_key}')
        grades[key] = grade
    assigned = defaultdict(list)
    scope_item_keys = set()
    for pair in data.scope.expected_pairs:
        item = items[pair.item_key]
        scope_item_keys.add(pair.item_key)
        for chapter, weight in item.chapter_weights.items():
            assigned[pair.student_key, chapter].append((pair, item, weight))
    estimates = []
    for student in sorted(data.scope.student_keys):
        for chapter in sorted(data.chapter_taxonomy, key=lambda c: c.order):
            rows = sorted(assigned[student, chapter.code], key=lambda row: row[0].item_key)
            scored = [(pair, item, weight, grades[student, pair.item_key].normalized_score)
                      for pair, item, weight in rows if pair.state == 'SCORED']
            n, n_assigned = len(scored), len(rows)
            w = sum((r[2] for r in scored), Decimal(0))
            w_assigned = sum((r[2] for r in rows), Decimal(0))
            coverage = Decimal(n)/n_assigned if n_assigned else None
            values = [r[3] for r in scored]
            value = sum((r[2]*r[3] for r in scored), Decimal(0))/w if n else None
            if not n_assigned:
                status = 'NOT_COVERED'
            elif not n:
                status = 'NO_EVIDENCE'
            elif n < data.parameters.min_items or coverage < data.parameters.min_coverage_items:
                status = 'LOW_EVIDENCE'
            else:
                status = 'OK'
            flags = []
            if n and min(values) == max(values):
                flags.append('ALL_ZERO' if values[0] == 0 else 'ALL_ONE' if values[0] == 1 else 'ALL_EQUAL_NON_EXTREME')
            by_type = {}
            for kind in ('PROGRAMMING', 'SUBJECTIVE'):
                part = [r for r in scored if ('PROGRAMMING' if r[1].item_type == 'PROGRAMMING' else 'SUBJECTIVE') == kind]
                if part:
                    part_w = sum((r[2] for r in part), Decimal(0))
                    by_type[kind] = AbilityTypeEstimate(value=sum((r[2]*r[3] for r in part), Decimal(0))/part_w, n_items=len(part), W_sum=part_w)
            if len(by_type) == 2:
                flags.append('MIXED_TYPES')
            if any(len(r[1].chapter_weights) > 1 for r in rows):
                flags.append('CROSS_CHAPTER_ITEM')
            if coverage is not None and coverage < 1:
                flags.append('LOW_COVERAGE')
            estimates.append(AbilityEstimate(
                object_key=student, dimension=chapter.code, dimension_label=chapter.name,
                dimension_order=chapter.order, value=value, status=status,
                assigned_items=n_assigned, scored_items=n, n_items=n, W_sum=w, W_assigned=w_assigned,
                n_eff=w*w/sum((r[2]*r[2] for r in scored), Decimal(0)) if n else Decimal(0),
                coverage_items=coverage, coverage_weight=w/w_assigned if n_assigned else None,
                missing=AbilityMissing(pending=sum(r[0].state == 'PENDING' for r in rows),
                    not_submitted=sum(r[0].state == 'NOT_SUBMITTED' for r in rows),
                    invalid=sum(r[0].state == 'INVALID' for r in rows)),
                observed_min=min(values) if n else None, observed_max=max(values) if n else None,
                diagnostic_flags=flags, by_type=by_type, evidence_item_keys=[r[0].item_key for r in scored]))
    return AbilityOutputV2(source_kind=data.source_kind, results_snapshot_version=data.results_snapshot_version,
        scoring_policy_version=data.scoring_policy_version, chapter_taxonomy_version=data.chapter_taxonomy_version,
        chapter_mapping_version=data.chapter_mapping_version, estimates=estimates,
        diagnostics=AbilityDiagnostics(min_items=data.parameters.min_items,
            min_coverage_items=data.parameters.min_coverage_items,
            unmapped_item_count=sum(not items[k].chapter_weights for k in scope_item_keys), warnings=sorted(warnings)))
