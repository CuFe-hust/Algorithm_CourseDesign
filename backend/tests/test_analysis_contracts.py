from decimal import Decimal
import pytest
from app.analysis.framework.catalog import catalogue, invoke
from app.analysis.framework.contracts import digest
from app.analysis.framework.graph import STEPS


def allocation(n=6, k=2):
    return {'answers':[{'answer_key':f'a{i}', 'author_key':f'u{i}'} for i in range(n)],
            'reviewers':[f'u{i}' for i in range(n)], 'required_reviewers':k,
            'forbidden_edges':[], 'existing_edges':[], 'history':[]}


def call(key, payload, mode='REAL_INPUT'):
    return invoke(key, payload, mode=mode, seed=42, input_hash=digest(payload))


def test_catalogue_has_machine_readable_contracts_and_graph_coverage():
    rows=catalogue()
    assert len(rows)==15
    assert all(r['input_schema']['properties'] and r['output_schema']['properties'] for r in rows)
    assert {s.algorithm for s in STEPS if s.algorithm} == {r['key'] for r in rows}
    assert next(s for s in STEPS if s.key=='review_timing').dependencies==('collect_reviews',)
    assert 'aggregation' in next(s for s in STEPS if s.key=='deviation').dependencies


def test_matching_is_complete_deterministic_and_constrained():
    payload=allocation()
    a=call('allocation',payload);b=call('allocation',payload)
    assert a==b and not a.is_mock and a.status=='OK'
    edges=a.payload['edges']
    assert len(edges)==12 and len({(e['answer_key'],e['reviewer_key']) for e in edges})==12
    authors={v['answer_key']:v['author_key'] for v in payload['answers']}
    assert all(authors[e['answer_key']]!=e['reviewer_key'] for e in edges)
    assert call('allocation',allocation(2,2)).status=='INFEASIBLE'
    payload['forbidden_edges']=[{'answer_key':'a0','reviewer_key':'u1'}]
    assert {'answer_key':'a0','reviewer_key':'u1'} not in call('allocation',payload).payload['edges']


def aggregation(scores, minimum=2):
    return {'answers':['a1'], 'rubric_max':'100', 'minimum_samples':minimum,
            'evaluations':[{'evaluation_key':f'e{i}','answer_key':'a1','score':str(v),'weight':'1'} for i,v in enumerate(scores)]}


def test_aggregation_distinguishes_zero_missing_and_zero_weight():
    result=call('aggregation',aggregation([0,0]))
    assert result.status=='OK' and Decimal(result.payload['scores'][0]['normalized_score'])==0
    missing=call('aggregation',aggregation([20]))
    assert missing.status=='INSUFFICIENT_DATA' and missing.payload['scores'][0]['normalized_score'] is None
    p=aggregation([100,0]);p['evaluations'][1]['weight']='0'
    assert call('aggregation',p).status=='INSUFFICIENT_DATA'
    with pytest.raises(ValueError):call('aggregation',aggregation([101,10]))


def test_unimplemented_real_algorithm_never_silently_falls_back_to_mock():
    p={'answers':[{'answer_key':'a1','content':'synthetic answer'}]}
    result=call('ai_signal',p)
    assert result.status=='NOT_IMPLEMENTED' and not result.is_mock
    mock=call('ai_signal',p,'DEMO')
    assert mock.is_mock and mock==call('ai_signal',p,'DEMO')
