from copy import deepcopy
from decimal import Decimal, localcontext
import json
from pathlib import Path

import pytest

from app.analysis.framework.ability_contracts import AbilityInputV2
from app.analysis.algorithms.ability_b0 import analyze


def payload(scores=('0.8', '0.5', '1')):
    names = ['贪心算法', '分治算法', '动态规划', '图论', '搜索与回溯', '字符串', '排序与查找', '数据结构', '数学与数论', '位运算与杂项', '数组与模拟']
    return dict(contract_version='ability-b0-v1', source_kind='DATABASE',
        results_snapshot_version='results-v1', scoring_policy_version='scores-v1',
        chapter_taxonomy_version='chapter-taxonomy-v1', chapter_mapping_version='question-chapter-map-v1',
        scope=dict(scope_kind='COURSE', scope_label='course', student_keys=['s1', 's0'], assignment_ids=['a1'],
            expected_pairs=[dict(student_key='s1', item_key=f'i{i}', state='SCORED') for i in range(len(scores))]),
        chapter_taxonomy=[dict(order=i+1, code=f'CH{i+1:02}', name=n) for i, n in enumerate(names)],
        items=[dict(item_key=f'i{i}', item_code=f'CODE-P{i}', item_version='1',
            item_type='PROGRAMMING' if i != 1 else 'ALGORITHM_ANALYSIS', difficulty=3,
            max_score='100', chapter_weights={'CH01':'1'}) for i in range(len(scores))],
        grades=[dict(student_key='s1', item_key=f'i{i}', normalized_score=s, score_version='1',
            result_ref=f'r{i}', score_kind='PROGRAMMING_JUDGE' if i != 1 else 'SUBJECTIVE_AGGREGATE') for i,s in enumerate(scores)],
        parameters=dict(method='B0', min_items=3, min_coverage_items='0.5', merge_policy='CHAPTER_WEIGHT', include_unmapped=False, interval_policy='NONE'))


def run(p):
    return analyze(AbilityInputV2.model_validate(p))


def chapter(out, student='s1', code='CH01'):
    return next(e for e in out.estimates if e.object_key == student and e.dimension == code)


def test_weighted_mean_and_fixed_roster_axes_and_type_diagnostics():
    out = run(payload())
    assert len(out.estimates) == 22
    assert [e.dimension for e in out.estimates[:11]] == [f'CH{i:02}' for i in range(1,12)]
    assert all(e.status == 'NOT_COVERED' and e.value is None and e.coverage_items is None for e in out.estimates[:11])
    e = chapter(out)
    assert abs(e.value - Decimal('2.3') / 3) < Decimal('1e-25')
    assert (e.status, e.n_items, e.assigned_items, e.W_sum, e.n_eff) == ('OK', 3, 3, 3, 3)
    assert e.by_type['PROGRAMMING'].value == Decimal('0.9')
    assert e.by_type['SUBJECTIVE'].value == Decimal('0.5')
    assert 'MIXED_TYPES' in e.diagnostic_flags
    assert (e.observed_min, e.observed_max) == (Decimal('.5'), 1)
    assert out.source_kind == 'DATABASE' and out.implementation_version == '2'
    serialized = out.model_dump(mode='json')
    assert isinstance(serialized['estimates'][11]['value'], str)
    assert 'summary' not in serialized and 'interval_low' not in serialized['estimates'][11]


def test_cross_chapter_missing_coverage_and_unmapped_exclusion():
    p = payload()
    p['items'][0]['chapter_weights'] = {'CH01':'.5', 'CH02':'.5'}
    p['scope']['expected_pairs'][1]['state'] = 'PENDING'
    p['grades'].pop(1)
    p['items'][2]['chapter_weights'] = {}
    out = run(p)
    e = chapter(out)
    assert (e.value, e.W_sum, e.W_assigned, e.coverage_items) == (Decimal('.8'), Decimal('.5'), Decimal('1.5'), Decimal('.5'))
    assert abs(e.coverage_weight - Decimal(1)/3) < Decimal('1e-25')
    assert e.missing.pending == 1 and e.status == 'LOW_EVIDENCE'
    assert {'CROSS_CHAPTER_ITEM','LOW_COVERAGE'} <= set(e.diagnostic_flags)
    assert chapter(out, code='CH02').W_sum == Decimal('.5')
    assert out.diagnostics.unmapped_item_count == 1


@pytest.mark.parametrize('state,field', [('PENDING','pending'),('NOT_SUBMITTED','not_submitted'),('INVALID','invalid')])
def test_missing_is_null_not_zero(state,field):
    p=payload(('0',))
    p['scope']['expected_pairs'][0]['state']=state
    p['grades']=[]
    e=chapter(run(p))
    assert e.status == 'NO_EVIDENCE' and e.value is None
    assert getattr(e.missing,field)==1 and e.coverage_items==0 and e.observed_min is None


@pytest.mark.parametrize('score,flag', [('0','ALL_ZERO'),('1','ALL_ONE'),('.5','ALL_EQUAL_NON_EXTREME')])
def test_constant_scores_do_not_demote(score,flag):
    e=chapter(run(payload((score,)*3)))
    assert e.status=='OK' and e.value==Decimal(score) and flag in e.diagnostic_flags


@pytest.mark.parametrize('item_type', ['OPEN_QUESTION', 'PROOF'])
def test_native_subjective_question_types(item_type):
    p=payload()
    p['items'][1]['item_type']=item_type
    assert chapter(run(p)).by_type['SUBJECTIVE'].value == Decimal('.5')


def test_duplicate_identical_scores_deduplicate_with_warning():
    p=payload()
    p['grades'].append(deepcopy(p['grades'][0]))
    out=run(p)
    assert chapter(out).n_items==3 and out.diagnostics.warnings


@pytest.mark.parametrize('change', ['score','version','ref'])
def test_duplicate_conflicts_reject(change):
    p=payload()
    g=deepcopy(p['grades'][0])
    g[{'score':'normalized_score','version':'score_version','ref':'result_ref'}[change]]={'score':'.2','version':'2','ref':'other'}[change]
    p['grades'].append(g)
    with pytest.raises(ValueError,match='DUPLICATE_SCORE_CONFLICT'): run(p)


@pytest.mark.parametrize('case', ['weights_zero','weights_sum','unknown_chapter','duplicate_item','duplicate_pair','outside_roster','missing_grade','non_scored_grade','outside_grade','bad_taxonomy','extra','type_equal','score_range','empty_version'])
def test_reject_invalid_inputs(case):
    p=payload()
    if case=='weights_zero': p['items'][0]['chapter_weights']={'CH01':'0'}
    elif case=='weights_sum': p['items'][0]['chapter_weights']={'CH01':'.7'}
    elif case=='unknown_chapter': p['items'][0]['chapter_weights']={'CH12':'1'}
    elif case=='duplicate_item': p['items'].append(deepcopy(p['items'][0]))
    elif case=='duplicate_pair': p['scope']['expected_pairs'].append(deepcopy(p['scope']['expected_pairs'][0]))
    elif case=='outside_roster': p['scope']['expected_pairs'][0]['student_key']='other'
    elif case=='missing_grade': p['grades'].pop()
    elif case=='non_scored_grade': p['scope']['expected_pairs'][0]['state']='INVALID'
    elif case=='outside_grade': p['grades'][0]['student_key']='other'
    elif case=='bad_taxonomy': p['chapter_taxonomy'][0]['name']='wrong'
    elif case=='extra': p['unrecognized']='x'
    elif case=='type_equal': p['parameters']['merge_policy']='TYPE_EQUAL'
    elif case=='score_range': p['grades'][0]['normalized_score']='1.1'
    elif case=='empty_version': p['scoring_policy_version']=''
    with pytest.raises(ValueError): run(p)


def test_determinism_even_when_decimal_context_changes_and_inputs_reordered():
    p=payload()
    original=deepcopy(p)
    a=run(p).model_dump(mode='json')
    p['items'].reverse(); p['grades'].reverse(); p['scope']['expected_pairs'].reverse(); p['scope']['student_keys'].reverse()
    with localcontext() as ctx:
        ctx.prec=8
        b=run(p).model_dump(mode='json')
    assert a==b
    assert original['items'][0]['item_key']=='i0'


def test_shipped_mapping_and_taxonomy_are_versioned_complete():
    root=Path(__file__).resolve().parents[2]/'data'/'analysis'
    taxonomy=json.loads((root/'chapter-taxonomy.json').read_text(encoding='utf-8'))
    mapping=json.loads((root/'question-chapter-mapping.json').read_text(encoding='utf-8'))
    assert len(taxonomy['axes'])==11 and len(mapping['questions'])==120
    assert mapping['mapping_version']=='question-chapter-map-v1'
