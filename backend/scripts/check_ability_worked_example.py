"""Run the small B0 worked example used in the student-ability report.

The same problem code (P-001) appears in two assignments under different
item_key values. One copy is scored; the other is not submitted. The example
shows that B0 keeps the assignment instances independent and leaves missing
evidence null rather than zero.

Run from the repository root with the backend dependencies available, e.g.::

    PYTHONPATH=".report-tools;backend" python backend/scripts/check_ability_worked_example.py
"""
from __future__ import annotations

import json
from decimal import Decimal

from app.analysis.algorithms.ability_b0 import analyze
from app.analysis.framework.ability_contracts import AbilityInputV2

CHAPTER_NAMES = (
    '贪心算法', '分治算法', '动态规划', '图论', '搜索与回溯', '字符串',
    '排序与查找', '数据结构', '数学与数论', '位运算与杂项', '数组与模拟',
)


def payload() -> dict:
    return dict(
        contract_version='ability-b0-v1',
        source_kind='SYNTHETIC_FIXTURE',
        results_snapshot_version='worked-example-v1',
        scoring_policy_version='synthetic-policy-v1',
        chapter_taxonomy_version='chapter-taxonomy-v1',
        chapter_mapping_version='question-chapter-map-v1',
        scope=dict(
            scope_kind='COURSE',
            scope_label='合成小例：同一题库题跨两次作业',
            student_keys=['s1', 's2'],
            assignment_ids=['a1', 'a2'],
            expected_pairs=[
                dict(student_key='s1', item_key='item-11', state='SCORED'),
                dict(student_key='s1', item_key='item-21', state='NOT_SUBMITTED'),
                dict(student_key='s1', item_key='item-12', state='PENDING'),
                dict(student_key='s2', item_key='item-21', state='NOT_SUBMITTED'),
            ],
        ),
        chapter_taxonomy=[
            dict(order=index + 1, code=f'CH{index + 1:02}', name=name)
            for index, name in enumerate(CHAPTER_NAMES)
        ],
        items=[
            dict(item_key='item-11', item_code='P-001', item_version='1',
                 item_type='PROGRAMMING', difficulty=3, max_score='100',
                 chapter_weights={'CH01': '1'}),
            dict(item_key='item-21', item_code='P-001', item_version='1',
                 item_type='PROGRAMMING', difficulty=3, max_score='100',
                 chapter_weights={'CH01': '1'}),
            dict(item_key='item-12', item_code='P-002', item_version='1',
                 item_type='ALGORITHM_ANALYSIS', difficulty=3, max_score='100',
                 chapter_weights={'CH02': '1'}),
        ],
        grades=[
            dict(student_key='s1', item_key='item-11', normalized_score='1',
                 score_version='v1', result_ref='judge-11',
                 score_kind='PROGRAMMING_JUDGE'),
        ],
    )


def main() -> None:
    out = analyze(AbilityInputV2.model_validate(payload()))
    estimates = {(e.object_key, e.dimension): e for e in out.estimates}
    selected = {}
    for (student, chapter), estimate in estimates.items():
        if student == 's1' and chapter in ('CH01', 'CH02') or student == 's2' and chapter == 'CH01':
            selected[f'{student}/{chapter}'] = dict(
                value=None if estimate.value is None else str(estimate.value),
                status=estimate.status,
                assigned_items=estimate.assigned_items,
                scored_items=estimate.scored_items,
                W_sum=str(estimate.W_sum),
                W_assigned=str(estimate.W_assigned),
                coverage_items=None if estimate.coverage_items is None else str(estimate.coverage_items),
                coverage_weight=None if estimate.coverage_weight is None else str(estimate.coverage_weight),
                missing=estimate.missing.model_dump(),
                by_type={k: dict(value=str(v.value), n_items=v.n_items)
                         for k, v in estimate.by_type.items()},
            )
    print(json.dumps(dict(selected=selected, diagnostics=out.diagnostics.model_dump(mode='json')),
                     ensure_ascii=False, indent=2))

    assert selected['s1/CH01']['value'] == '1'
    assert selected['s1/CH01']['status'] == 'LOW_EVIDENCE'
    assert selected['s1/CH01']['assigned_items'] == 2
    assert selected['s1/CH01']['scored_items'] == 1
    assert selected['s1/CH01']['coverage_items'] == '0.5'
    assert selected['s1/CH02']['value'] is None
    assert selected['s1/CH02']['status'] == 'NO_EVIDENCE'
    assert selected['s1/CH02']['missing']['pending'] == 1
    assert selected['s2/CH01']['value'] is None
    assert selected['s2/CH01']['status'] == 'NO_EVIDENCE'
    assert selected['s2/CH01']['missing']['not_submitted'] == 1
    assert selected['s2/CH01']['W_sum'] == '0'
    print('WORKED EXAMPLE OK', file=__import__('sys').stderr)


if __name__ == '__main__':
    main()
