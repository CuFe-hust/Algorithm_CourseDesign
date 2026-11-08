"""Independent exact oracles and representative statistical edge cases."""
from itertools import product,combinations
from collections import Counter
from decimal import Decimal
import random,time
import pytest
from app.analysis.framework.contracts import AllocationInput,DetectionInput,TimingInput,AggregationInput
from app.analysis.algorithms import review,baseline


def test_min_cost_flow_matches_exhaustive_convex_load_optimum():
    rng=random.Random(20261027)
    for _ in range(24):
        reviewers=['u0','u1','u2','u3']
        answers=[dict(answer_key=f'a{i}',author_key=f'u{i}') for i in range(3)]
        forbidden=[dict(answer_key=a['answer_key'],reviewer_key=r) for a in answers for r in reviewers if rng.random()<.12]
        data=AllocationInput(answers=answers,reviewers=reviewers,required_reviewers=1,forbidden_edges=forbidden,
            prior_loads={r:rng.randrange(3) for r in reviewers},max_tasks_per_reviewer=4)
        blocked={(e.answer_key,e.reviewer_key) for e in data.forbidden_edges}
        choices=[[r for r in reviewers if r!=a['author_key'] and (a['answer_key'],r) not in blocked] for a in answers]
        values=[]
        for plan in product(*choices):
            loads=Counter(plan)
            if all(loads[r]+data.prior_loads[r]<=4 for r in reviewers):values.append(sum((loads[r]+data.prior_loads[r])**2 for r in reviewers))
        result=review.allocation(data)
        assert result.feasible==bool(values)
        if values:assert sum((result.load_metrics[r]+data.prior_loads[r])**2 for r in reviewers)==min(values)
        else:assert not result.edges


def test_global_capacity_infeasible_never_returns_partial_plan():
    d=AllocationInput(answers=[dict(answer_key=f'a{i}',author_key=f'u{i}') for i in range(3)],reviewers=['u0','u1','u2'],required_reviewers=2,max_tasks_per_reviewer=1)
    result=review.allocation(d)
    assert not result.feasible and result.edges==[] and result.unmet_constraints


def test_cohort_217_deterministic_balanced_and_anonymous():
    d=AllocationInput(answers=[dict(answer_key=f'a{i}',author_key=f'u{i}') for i in range(217)],reviewers=[f'u{i}' for i in range(217)],required_reviewers=3,seed=17)
    result=review.allocation(d)
    assert result.feasible and len(result.edges)==651 and set(result.load_metrics.values())=={3}
    assert all(e.reviewer_key!='u'+e.answer_key[1:] for e in result.edges)
    # Small deterministic replay avoids doubling the full-cohort performance experiment.
    small=d.model_copy(update={'answers':d.answers[:4],'reviewers':d.reviewers[:4]})
    assert review.allocation(small)==review.allocation(small)


def test_deviation_uses_other_reviewers_and_ignores_zero_weight():
    es=[dict(evaluation_key=f'e{i}',answer_key='a',reviewer_key=f'u{i}',score=score) for i,score in enumerate([10,90,90])]
    d=DetectionInput(evaluations=es,baseline=[],rubric_max=100,minimum_samples=2,threshold='.2')
    result=review.deviation(d)
    assert next(s for s in result.signals if s.object_key=='e0').value==Decimal('.8')
    sparse=d.model_copy(update={'evaluations':d.evaluations[:2]});r=review.deviation(sparse)
    assert r.sample_count==0 and r.missing_count==2


def test_historical_bias_and_reciprocal_ring_have_auditable_evidence():
    current=[dict(evaluation_key='now',answer_key='current',reviewer_key='u1',score=80)]
    hist=[dict(evaluation_key=f'h{i}',answer_key=f'a{i}',reviewer_key='u1',score=90) for i in range(3)]
    refs=[dict(answer_key=f'a{i}',normalized_score='.5',valid_count=3,dispersion=None,reason=None) for i in range(3)]
    d=DetectionInput(evaluations=current,baseline=[],history=hist,history_baseline=refs,rubric_max=100,minimum_samples=3,threshold='.2')
    assert review.reviewer_bias(d).signals[0].value==Decimal('.4')
    ring=d.model_copy(update={'minimum_samples':2,'history':[d.history[0],d.history[1].model_copy(update={'reviewer_key':'u2'})],
        'author_map':{'a0':'u2','a1':'u1'}})
    rel=review.relationship(ring)
    assert len(rel.signals)==1 and rel.signals[0].kind=='RECIPROCAL_HIGH_SCORE_COMPONENT'


def test_timing_zero_is_observed_and_missing_stays_missing():
    d=TimingInput(timings=[dict(task_key=f't{i}',elapsed_seconds=s) for i,s in enumerate([0,100,100,None])],minimum_samples=3)
    r=review.review_timing(d)
    assert r.sample_count==3 and r.missing_count==1 and r.signals[0].object_key=='t0'


def test_weighted_median_and_mean_keep_partial_results():
    d=AggregationInput(answers=['a','missing'],rubric_max=100,minimum_samples=2,method='weighted_median',evaluations=[
        dict(evaluation_key='e1',answer_key='a',score=10,weight=1),dict(evaluation_key='e2',answer_key='a',score=90,weight=2)])
    r=baseline.aggregation(d)
    assert r.scores[0].normalized_score==Decimal('.9') and r.scores[1].normalized_score is None
    assert baseline.aggregation(d.model_copy(update={'method':'weighted_mean'})).scores[0].normalized_score==(Decimal(190)/300).quantize(Decimal(".000001"))


def test_degenerate_server_time_baseline_is_insufficient_not_clean():
    from app.analysis.framework.catalog import invoke
    from app.analysis.framework.contracts import digest
    payload=dict(timings=[dict(task_key=str(i),elapsed_seconds='0') for i in range(5)],minimum_samples=5)
    result=invoke('review_timing',payload,mode='REAL_INPUT',seed=1,input_hash=digest(payload))
    assert result.status=='INSUFFICIENT_DATA' and result.limitations and not result.is_mock
