from collections import Counter
from decimal import Decimal
from app.analysis.framework.contracts import AllocationOutput, AggregationOutput, AggregatedScore
from app.analysis.algorithms import similarity as similarity_engine


def allocation(data):
    authors = {a.answer_key:a.author_key for a in data.answers}
    if len(authors)!=len(data.answers) or len(set(data.reviewers))!=len(data.reviewers):
        raise ValueError('Duplicate stable keys')
    if any(e.answer_key not in authors or e.reviewer_key not in data.reviewers
           for e in [*data.forbidden_edges,*data.existing_edges]):
        raise ValueError('Edge references are outside the current snapshot')
    forbidden={(e.answer_key,e.reviewer_key) for e in [*data.forbidden_edges,*data.existing_edges]}
    load=Counter({r:0 for r in data.reviewers})
    history=Counter((e.answer_key,e.reviewer_key) for e in data.history)
    edges=[];unmet=[] if data.answers else ['NO_ANSWERS']
    for answer in sorted(data.answers,key=lambda a:a.answer_key):
        eligible=[r for r in data.reviewers if r!=answer.author_key and (answer.answer_key,r) not in forbidden]
        if len(eligible)<data.required_reviewers:
            unmet.append(f'{answer.answer_key}: needs {data.required_reviewers}, eligible {len(eligible)}')
            continue
        eligible.sort(key=lambda r:(load[r],history[(answer.answer_key,r)],r))
        for reviewer in eligible[:data.required_reviewers]:
            edges.append(dict(answer_key=answer.answer_key,reviewer_key=reviewer));load[reviewer]+=1
    # An incomplete mapping must never look publishable.
    return AllocationOutput(feasible=not unmet,edges=[] if unmet else edges,
        unmet_constraints=unmet,load_metrics=dict(load))


def aggregation(data):
    if len(set(data.answers))!=len(data.answers):raise ValueError('Duplicate answer keys')
    keys=set();scores=[]
    for e in data.evaluations:
        if e.answer_key not in data.answers or e.evaluation_key in keys or e.score>data.rubric_max:
            raise ValueError('Invalid evaluation reference or score')
        keys.add(e.evaluation_key)
    for answer in data.answers:
        rows=[e for e in data.evaluations if e.answer_key==answer and e.weight>0]
        enough=len(rows)>=data.minimum_samples
        mean=sum((e.score/data.rubric_max*e.weight for e in rows),Decimal(0))/sum((e.weight for e in rows),Decimal(1) if not rows else Decimal(0))
        spread=(max(e.score for e in rows)-min(e.score for e in rows))/data.rubric_max if rows else None
        scores.append(AggregatedScore(answer_key=answer,normalized_score=mean.quantize(Decimal('.000001')) if enough else None,
            valid_count=len(rows),dispersion=spread,reason=None if enough else 'MINIMUM_SAMPLES_NOT_MET'))
    return AggregationOutput(scores=scores)


def behavior(data):
    kinds=set(data.available_event_types)
    if any(e.kind not in kinds for e in data.events):raise ValueError('Unrecorded event type')
    return dict(counts=dict(Counter(e.kind for e in data.events)),available_event_types=sorted(kinds),
        limitations=['Counts describe recorded events only; no inference of effort or AI usage.'])


def statistics(data):
    roster=set(data.roster)
    if len(roster)!=len(data.roster) or not set(data.submitted)<=roster or any(g.student_key not in roster for g in data.grades):
        raise ValueError('Statistics population mismatch')
    valid=[g.normalized_score for g in data.grades if g.normalized_score is not None]
    completed={g.student_key for g in data.grades if g.normalized_score is not None}
    return dict(denominator=len(roster),submitted_count=len(set(data.submitted)),completed_count=len(completed),
        missing_count=len(roster-completed),mean_score=sum(valid)/len(valid) if valid else None)


def code_similarity(data):
    """Token-level code similarity over submissions of one assignment item.

    The scope guard lives here as well as in the framework so a direct offline
    call cannot compare answers of different questions: a pair spanning two
    items would be meaningless evidence for a teacher.
    """
    items = {answer.answer_key: getattr(answer, 'item_key', None) for answer in data.answers}
    scopes = {value for value in items.values() if value is not None}
    if len(scopes) > 1:
        raise ValueError('Similarity requires a single assignment item scope')
    result = similarity_engine.compare(
        [dict(answer_key=answer.answer_key, content=answer.content, language=answer.language)
         for answer in data.answers],
        minimum_tokens=data.minimum_tokens,
        threshold=float(data.threshold))
    return {
        'pairs': result.pairs,
        'method': 'winnowing_token_k12_w4',
        'clusters': result.clusters,
        'insufficient': result.insufficient,
        'submission_count': result.submission_count,
        'pairs_truncated': result.pairs_truncated,
        'parameters': {'k': similarity_engine.KGRAM, 'window': similarity_engine.WINDOW,
                       'minimum_tokens': data.minimum_tokens,
                       'threshold': str(data.threshold)},
    }
