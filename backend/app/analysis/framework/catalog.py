from dataclasses import dataclass
from . import contracts as c
from app.analysis.algorithms import baseline, mock, review


@dataclass(frozen=True)
class Plugin:
    key:str
    label:str
    input:type[c.Contract]
    output:type[c.Contract]
    implementation:str
    version:str='1'


PLUGINS={p.key:p for p in [
    Plugin('judge_adapter','已有评测适配',c.JudgeInput,c.JudgeOutput,'existing_judge_adapter'),
    Plugin('allocation','评审匹配',c.AllocationInput,c.AllocationOutput,'convex_load_min_cost_flow','2'),
    Plugin('aggregation','评分聚合',c.AggregationInput,c.AggregationOutput,'explicit_weighted_aggregation','2'),
    *[Plugin(k,label,c.DetectionInput,c.SignalOutput,'auditable_review_signals','2') for k,label in
      [('deviation','单次偏离'),('reviewer_bias','长期偏差'),('relationship','异常关系')]],
    Plugin('review_timing','评价时长',c.TimingInput,c.SignalOutput,'server_duration_baseline','2'),
    Plugin('code_similarity','代码相似',c.ContentInput,c.SimilarityOutput,'winnowing_token','2'),
    Plugin('text_similarity','文本相似',c.ContentInput,c.SimilarityOutput,'not_implemented'),
    Plugin('ai_signal','AI辅助信号',c.ContentInput,c.SignalOutput,'not_implemented'),
    *[Plugin(k,label,c.LearningInput,c.LearningOutput,'not_implemented') for k,label in
      [('mastery','知识点掌握'),('ability','学生能力'),('empirical_difficulty','经验难度')]],
    Plugin('behavior','学习行为',c.BehaviorInput,c.BehaviorOutput,'event_counts_baseline'),
    Plugin('statistics','基础统计',c.StatisticsInput,c.StatisticsOutput,'descriptive_statistics'),
]}

# Separate versioned extension: legacy catalog/examples and historical runs stay intact.
def get_plugin(key):
    if key == 'ability_d1':
        from .difficulty_contracts import DifficultyInputV1, DifficultyOutputV1
        return Plugin('ability_d1','难度感知章节模型',DifficultyInputV1,DifficultyOutputV1,'difficulty_fractional','2')
    if key == 'ability_b0':
        from .ability_contracts import AbilityInputV2, AbilityOutputV2
        return Plugin('ability_b0','章节作答表现 B0',AbilityInputV2,AbilityOutputV2,'ability_b0','2')
    return PLUGINS[key]


def catalogue():
    return [dict(key=p.key,label=p.label,implementation=p.implementation,implementation_version=p.version,
        schema_version='analysis-v2',input_schema=p.input.model_json_schema(),output_schema=p.output.model_json_schema(mode='serialization'),
        mock_available=p.implementation=='not_implemented') for p in PLUGINS.values()]


def invoke(key,payload,*,mode,seed,input_hash):
    if mode not in ('DEMO','REAL_INPUT'):raise ValueError('Invalid analysis mode')
    if c.digest(payload)!=input_hash:raise ValueError('Input hash mismatch')
    plugin=get_plugin(key);data=plugin.input.model_validate(payload)
    is_mock=mode=='DEMO';status='OK';limitations=[]
    implementation=plugin.implementation
    if implementation=='not_implemented' and mode=='REAL_INPUT':
        status='NOT_IMPLEMENTED';output={};limitations=['Research implementation not installed.']
    else:
        if implementation=='not_implemented':
            output=mock.simulate(key,data,seed);implementation='synthetic_demo'
            limitations=['Synthetic demonstration only; not research evidence or a formal grade.']
        elif key in ('ability_b0','ability_d1'):
            if key=='ability_b0':
                from app.analysis.algorithms.ability_b0 import analyze
                source_kind=data.source_kind
            else:
                from app.analysis.algorithms.ability_difficulty import analyze
                source_kind=data.learning_input.source_kind
            if mode=='REAL_INPUT' and source_kind!='DATABASE':
                raise ValueError('Synthetic input cannot be used as formal evidence')
            output=analyze(data)
            is_mock=is_mock or source_kind!='DATABASE'
            if is_mock:limitations=['Synthetic input; deterministic algorithm calculation, not real student evidence.']
            if key=='ability_d1':
                limitations+=['Reference expected score under a fitted model, not a mastery probability or a confidence interval.']
        elif key=='judge_adapter':
            output=dict(results=data.results,score_available=False,reason='WEIGHTED_CASE_EVIDENCE_UNAVAILABLE')
            is_mock=is_mock or any(r.is_mock for r in data.results)
        elif key in ('allocation','deviation','reviewer_bias','review_timing','relationship'):
            output=getattr(review,key)(data)
        else:output=getattr(baseline,key)(data)
        typed_output=plugin.output.model_validate(output.model_dump() if isinstance(output,c.Contract) else output)
        from .validation import validate_output
        validate_output(key,data,typed_output)
        output=typed_output.model_dump(mode='json')
        if key in ('ability_b0','ability_d1') and not any(e['value'] is not None for e in output['estimates']):status='INSUFFICIENT_DATA'
        if key=='allocation' and not output['feasible']:status='INFEASIBLE'
        if key=='aggregation' and any(s['normalized_score'] is None for s in output['scores']):status='INSUFFICIENT_DATA'
        if key in ('deviation','reviewer_bias','relationship') and (not output['sample_count'] or output['missing_count']):
            status='INSUFFICIENT_DATA'
        if key=='review_timing' and (output['sample_count']<data.minimum_samples or output['missing_count']):
            status='INSUFFICIENT_DATA'
        if key=='review_timing':
            from statistics import median
            durations=[t.elapsed_seconds for t in data.timings if t.elapsed_seconds is not None]
            if durations and median(durations)==0:
                status='INSUFFICIENT_DATA';limitations.append('ZERO_DURATION_BASELINE: relative timing evidence is unavailable.')
    return c.AlgorithmOutput(algorithm_key=key,implementation_name=implementation,implementation_version=plugin.version,input_hash=input_hash,
        is_mock=is_mock,status=status,payload=output,limitations=limitations)
