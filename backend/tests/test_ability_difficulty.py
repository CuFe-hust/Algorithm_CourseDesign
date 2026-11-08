from copy import deepcopy
from decimal import Decimal
import pytest
from test_ability_b0 import payload
from app.analysis.framework.difficulty_contracts import DifficultyInputV1
from app.analysis.algorithms.ability_difficulty import analyze


def run(p,processes=None):
    return analyze(DifficultyInputV1.model_validate(dict(learning_input=p,processes=processes or [])))


def test_decimal_mapping_precision_is_normalized_without_mutating_snapshot():
    p=payload()
    for item in p['items']:
        item['chapter_weights']={'CH01':'0.333333','CH02':'0.333333','CH03':'0.333333'}
    before=deepcopy(p)
    out=run(p)
    assert p==before and out.model_diagnostics['converged']
    assert len(out.estimates)==22
    assert all(e.value is None for e in out.estimates if e.status=='NOT_COVERED')


def test_process_is_observed_diagnostic_and_not_used_to_score():
    p=payload(('0.8',))
    events=[dict(student_key='s1',item_key='i0',sequence_no=i,verdict=v,score=y)
            for i,v,y in [(1,'CE',None),(2,'WA','0.4'),(3,'WA','0.8')]]
    a=run(p);b=run(p,events)
    assert a.estimates==b.estimates
    row=next(r for r in b.process_diagnostics if r['object_key']=='s1')['items'][0]
    assert row['submission_count']==3 and row['first_score'] is None
    assert row['first_accepted_attempt'] is None and row['repeated_failure_pairs']==1
    assert Decimal(row['latest_score'])==Decimal('.8')


def test_no_evidence_gets_no_prior_point_and_empty_process_is_unavailable():
    p=payload(('0',))
    p['scope']['expected_pairs'][0]['state']='PENDING';p['grades']=[]
    out=run(p)
    assert all(e.value is None and e.theta is None for e in out.estimates)
    assert all(not s['available'] for s in out.process_diagnostics)


def test_process_cannot_reference_someone_outside_scope():
    event=dict(student_key='other',item_key='i0',sequence_no=1,verdict='WA',score='0')
    with pytest.raises(ValueError,match='PROCESS_OUTSIDE_SCOPE'):
        run(payload(),[event])


def test_process_gaps_do_not_become_fake_adjacent_attempts():
    events=[dict(student_key='s1',item_key='i0',sequence_no=i,verdict=v,score=y)
            for i,v,y in [(2,'WA','0.2'),(4,'WA','0.4'),(7,'AC','1')]]
    out=run(payload(('1',)),events)
    row=next(r for r in out.process_diagnostics if r['object_key']=='s1')['items'][0]
    assert row['first_accepted_attempt']==7
    assert row['repeated_failure_pairs']==0


def test_fixed_difficulty_ablation_does_not_claim_cohort_calibration():
    data=DifficultyInputV1.model_validate(dict(learning_input=payload(),model_parameters={'calibrate_items':False}))
    assert analyze(data).model_diagnostics['difficulty_source']=='FIXED_TEACHER_PRIOR'
