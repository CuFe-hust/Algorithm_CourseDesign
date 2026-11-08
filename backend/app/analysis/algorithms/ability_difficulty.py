"""Pure difficulty-model adapter; preserves descriptive B0 and missing evidence."""
import math
from collections import defaultdict
from .ability_b0 import analyze as baseline
from .difficulty_model import Item, Observation, fit
from ..framework.difficulty_contracts import DifficultyInputV1, DifficultyOutputV1, DifficultyEstimate


def sigmoid(x):
    if x>=0:return 1/(1+math.exp(-x))
    e=math.exp(x);return e/(1+e)


def process_summary(data):
    by_student=defaultdict(lambda:defaultdict(list))
    for event in data.processes:
        by_student[event.student_key][event.item_key].append(event)
    output=[]
    for student in sorted(data.learning_input.scope.student_keys):
        items=[]
        for key,events in sorted(by_student[student].items()):
            events=sorted(events,key=lambda e:e.sequence_no)
            values=[float(e.score) for e in events if e.score is not None]
            accepted=next((e.sequence_no for e in events if e.verdict=='AC'),None)
            items.append(dict(item_key=key,submission_count=len(events),
                first_score=str(events[0].score) if events[0].score is not None else None,
                latest_score=str(events[-1].score) if events[-1].score is not None else None,
                best_score=str(max(values)) if values else None,first_accepted_attempt=accepted,
                repeated_failure_pairs=sum(a.verdict==b.verdict and a.verdict!='AC' and b.sequence_no==a.sequence_no+1
                    for a,b in zip(events,events[1:]))))
        output.append(dict(object_key=student,available=bool(items),items=items,
                           semantics='OBSERVED_PROCESS_ONLY_NOT_ABILITY_SCORE'))
    return output


def analyze(data:DifficultyInputV1)->DifficultyOutputV1:
    data=DifficultyInputV1.model_validate(data.model_dump())
    learning=data.learning_input
    raw=baseline(learning)
    known={i.item_key:i for i in learning.items if i.chapter_weights}
    # Database decimal shares permit tiny rounding error; normalize that accepted
    # representation for the floating-point model without changing the snapshot.
    items=[Item(key=i.item_key,weights={c:float(w)/float(sum(i.chapter_weights.values()))
           for c,w in i.chapter_weights.items()},difficulty=i.difficulty) for i in known.values()]
    rows=[Observation(student=g.student_key,item=g.item_key,score=float(g.normalized_score))
          for g in learning.grades if g.item_key in known]
    model=fit(items,rows,**data.model_parameters.model_dump())
    estimates=[]
    for e in raw.estimates:
        theta=model.theta.get(e.object_key,{}).get(e.dimension) if e.value is not None else None
        value=str(sigmoid(theta)) if theta is not None else None
        estimates.append(DifficultyEstimate.model_validate(dict(e.model_dump(),
            baseline_value=e.value,value=value,theta=theta)))
    return DifficultyOutputV1(**{k:getattr(raw,k) for k in (
        'source_kind','results_snapshot_version','scoring_policy_version','chapter_taxonomy_version','chapter_mapping_version')},
        model_parameters=data.model_parameters,estimates=estimates,
        model_diagnostics=dict(loss=model.loss,iterations=model.iterations,converged=model.converged,
            score_semantics='REFERENCE_EXPECTED_SCORE',reference_difficulty=0,
            difficulty_source='TEACHER_PRIOR_WITH_COHORT_CALIBRATION' if data.model_parameters.calibrate_items else 'FIXED_TEACHER_PRIOR',
            n_observations=len({(r.student,r.item) for r in rows}),n_items=len(items),
            warnings=[] if model.converged else ['OPTIMIZATION_NOT_CONVERGED_PROVISIONAL_OUTPUT']),
        process_diagnostics=process_summary(data))
