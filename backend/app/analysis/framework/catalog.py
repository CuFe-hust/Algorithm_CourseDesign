from dataclasses import dataclass
from . import contracts as c
from app.analysis.algorithms import baseline, mock


@dataclass(frozen=True)
class Plugin:
    key:str
    label:str
    input:type[c.Contract]
    output:type[c.Contract]
    implementation:str


PLUGINS={p.key:p for p in [
    Plugin('judge_adapter','已有评测适配',c.JudgeInput,c.JudgeOutput,'existing_judge_adapter'),
    Plugin('allocation','评审匹配',c.AllocationInput,c.AllocationOutput,'balanced_greedy_baseline'),
    Plugin('aggregation','评分聚合',c.AggregationInput,c.AggregationOutput,'weighted_mean_baseline'),
    *[Plugin(k,label,c.DetectionInput,c.SignalOutput,'not_implemented') for k,label in
      [('deviation','单次偏离'),('reviewer_bias','长期偏差'),('relationship','异常关系')]],
    Plugin('review_timing','评价时长',c.TimingInput,c.SignalOutput,'not_implemented'),
    *[Plugin(k,label,c.ContentInput,c.SimilarityOutput,'not_implemented') for k,label in
      [('code_similarity','代码相似'),('text_similarity','文本相似')]],
    Plugin('ai_signal','AI辅助信号',c.ContentInput,c.SignalOutput,'not_implemented'),
    *[Plugin(k,label,c.LearningInput,c.LearningOutput,'not_implemented') for k,label in
      [('mastery','知识点掌握'),('ability','学生能力'),('empirical_difficulty','经验难度')]],
    Plugin('behavior','学习行为',c.BehaviorInput,c.BehaviorOutput,'event_counts_baseline'),
    Plugin('statistics','基础统计',c.StatisticsInput,c.StatisticsOutput,'descriptive_statistics'),
]}


def catalogue():
    return [dict(key=p.key,label=p.label,implementation=p.implementation,implementation_version='1',
        schema_version='analysis-v1',input_schema=p.input.model_json_schema(),output_schema=p.output.model_json_schema(mode='serialization'),
        mock_available=p.implementation=='not_implemented') for p in PLUGINS.values()]


def invoke(key,payload,*,mode,seed,input_hash):
    if mode not in ('DEMO','REAL_INPUT'):raise ValueError('Invalid analysis mode')
    if c.digest(payload)!=input_hash:raise ValueError('Input hash mismatch')
    plugin=PLUGINS[key];data=plugin.input.model_validate(payload)
    is_mock=mode=='DEMO';status='OK';limitations=[]
    implementation=plugin.implementation
    if implementation=='not_implemented' and mode=='REAL_INPUT':
        status='NOT_IMPLEMENTED';output={};limitations=['Research implementation not installed.']
    else:
        if implementation=='not_implemented':
            output=mock.simulate(key,data,seed);implementation='synthetic_demo'
            limitations=['Synthetic demonstration only; not research evidence or a formal grade.']
        elif key=='judge_adapter':
            output=dict(results=data.results,score_available=False,reason='WEIGHTED_CASE_EVIDENCE_UNAVAILABLE')
            is_mock=is_mock or any(r.is_mock for r in data.results)
        else:output=getattr(baseline,key)(data)
        output=plugin.output.model_validate(output.model_dump() if isinstance(output,c.Contract) else output).model_dump(mode='json')
        if key=='allocation' and not output['feasible']:status='INFEASIBLE'
        if key=='aggregation' and any(s['normalized_score'] is None for s in output['scores']):status='INSUFFICIENT_DATA'
    return c.AlgorithmOutput(algorithm_key=key,implementation_name=implementation,input_hash=input_hash,
        is_mock=is_mock,status=status,payload=output,limitations=limitations)
