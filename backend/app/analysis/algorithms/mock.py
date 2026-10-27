"""Deterministic demonstrations, never used as a real algorithm fallback."""
from decimal import Decimal
import random
from app.analysis.framework.contracts import digest


def simulate(key, data, seed):
    rng=random.Random(f'{seed}:{key}:{digest(data.model_dump(mode="json"))}')
    if key in ('code_similarity','text_similarity'):
        pairs=[]
        if len(data.answers)>=2:
            left,right=data.answers[:2]
            pairs=[dict(left_key=left.answer_key,right_key=right.answer_key,
                similarity=str(Decimal(rng.randint(10,90))/100),matching_spans=[])]
        return dict(pairs=pairs,method='synthetic-demo-only')
    if key in ('mastery','ability','empirical_difficulty'):
        groups={}
        for g in data.grades:
            dimensions=list(g.knowledge_weights) if key=='mastery' else ['ability' if key=='ability' else g.item_key]
            for dimension in dimensions:
                object_key=g.item_key if key=='empirical_difficulty' else g.student_key
                groups.setdefault((object_key,dimension),[]).append(g.normalized_score)
        return dict(estimates=[dict(object_key=obj,dimension=dim,value=str(Decimal(rng.randint(20,95))/100),
            sample_count=sum(v is not None for v in values),missing_count=sum(v is None for v in values))
            for (obj,dim),values in sorted(groups.items())])
    if key=='ai_signal':
        keys=[a.answer_key for a in data.answers]
    elif key=='review_timing':
        keys=[t.task_key for t in data.timings if t.elapsed_seconds is not None]
    else:
        keys=[e.evaluation_key for e in data.evaluations]
    # No simulated accusation, identity decision or AI probability.
    return dict(signals=[dict(object_key=keys[0],kind='SYNTHETIC_EXAMPLE',value=None,
        explanation='Demonstration fixture; not a real detected anomaly.')] if keys else [],
        sample_count=len(keys),missing_count=0)
