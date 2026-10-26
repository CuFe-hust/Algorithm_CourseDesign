"""Framework invariants checked independently of replacement algorithms."""
from collections import Counter


def validate_output(key,data,result):
    if key=='allocation':
        authors={a.answer_key:a.author_key for a in data.answers}
        edges=[(e.answer_key,e.reviewer_key) for e in result.edges]
        forbidden={(e.answer_key,e.reviewer_key) for e in [*data.forbidden_edges,*data.existing_edges]}
        if len(edges)!=len(set(edges)) or any(a not in authors or r not in data.reviewers
                or r==authors.get(a) or (a,r) in forbidden for a,r in edges):
            raise ValueError('Matcher violated references, uniqueness or forbidden relations')
        if result.feasible:
            counts=Counter(a for a,_ in edges)
            loads=Counter(r for _,r in edges)
            if not authors or any(counts[a]!=data.required_reviewers for a in authors) or result.unmet_constraints:
                raise ValueError('Matcher returned an incomplete feasible plan')
            if result.load_metrics!={r:loads[r] for r in data.reviewers}:
                raise ValueError('Matcher workload metrics do not match edges')
        elif result.edges or not result.unmet_constraints:
            raise ValueError('Infeasible output must explain failure and not expose a partial plan')
    elif key=='aggregation':
        ids=[s.answer_key for s in result.scores]
        if len(ids)!=len(set(ids)) or set(ids)!=set(data.answers):
            raise ValueError('Aggregator must return exactly the input answer keys')
        for score in result.scores:
            valid=sum(e.answer_key==score.answer_key and e.weight>0 for e in data.evaluations)
            if score.valid_count!=valid or (score.normalized_score is not None)!=(valid>=data.minimum_samples):
                raise ValueError('Aggregator violated sample/missingness invariants')
    elif key in ('code_similarity','text_similarity'):
        known={a.answer_key for a in data.answers};seen=set()
        for pair in result.pairs:
            relation=tuple(sorted((pair.left_key,pair.right_key)))
            if pair.left_key not in known or pair.right_key not in known or pair.left_key==pair.right_key or relation in seen:
                raise ValueError('Similarity pair is not a unique pair of source answers')
            seen.add(relation)
    elif key in ('mastery','ability','empirical_difficulty'):
        known={g.item_key if key=='empirical_difficulty' else g.student_key for g in data.grades}
        if any(e.object_key not in known for e in result.estimates):raise ValueError('Unknown learning subject')
        ids=[(e.object_key,e.dimension) for e in result.estimates]
        if len(ids)!=len(set(ids)):raise ValueError('Duplicate learning estimate')
    elif key in ('deviation','reviewer_bias','relationship','review_timing','ai_signal'):
        if key=='ai_signal':known={a.answer_key for a in data.answers}
        elif key=='review_timing':known={t.task_key for t in data.timings}
        else:
            known={e.evaluation_key for e in data.evaluations}|{e.answer_key for e in data.evaluations}
            known|={e.reviewer_key for e in data.evaluations if e.reviewer_key is not None}
        if any(s.object_key not in known for s in result.signals):raise ValueError('Unknown signal subject')
