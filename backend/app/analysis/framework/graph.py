from dataclasses import dataclass


@dataclass(frozen=True)
class Step:
    key:str
    dependencies:tuple[str,...]=()
    algorithm:str|None=None
    event:str|None=None


STEPS=(
    Step('judge_adapter',algorithm='judge_adapter'),
    Step('code_similarity',algorithm='code_similarity'),
    Step('text_similarity',algorithm='text_similarity'),
    Step('ai_signal',algorithm='ai_signal'),
    Step('behavior',algorithm='behavior'),
    Step('allocation',algorithm='allocation'),
    Step('open_review',('allocation',),event='OPEN_REVIEW'),
    Step('collect_reviews',('open_review',),event='SUBMIT_REVIEWS'),
    Step('aggregation',('collect_reviews',),algorithm='aggregation'),
    Step('review_timing',('collect_reviews',),algorithm='review_timing'),
    Step('deviation',('aggregation',),algorithm='deviation'),
    Step('reviewer_bias',('aggregation',),algorithm='reviewer_bias'),
    Step('relationship',('aggregation',),algorithm='relationship'),
    Step('resolve',('deviation','reviewer_bias','review_timing','relationship'),event='RESOLVE'),
    Step('supplement_allocation',('resolve',),algorithm='allocation'),
    Step('collect_supplement',('supplement_allocation',),event='SUBMIT_SUPPLEMENT'),
    Step('reaggregation',('resolve','collect_supplement'),algorithm='aggregation'),
    Step('item_scores',('judge_adapter','reaggregation')),
    Step('result_snapshot',('item_scores',)),
    Step('mastery',('result_snapshot',),algorithm='mastery'),
    Step('ability',('result_snapshot',),algorithm='ability'),
    Step('statistics',('result_snapshot',),algorithm='statistics'),
    Step('empirical_difficulty',('result_snapshot',),algorithm='empirical_difficulty'),
)
BY_KEY={step.key:step for step in STEPS}


def steps_for(batch):
    if batch.configuration.get('pipeline')=='STUDENT_ABILITY_D1':
        return (Step('ability',algorithm='ability_d1'),)
    if batch.configuration.get('pipeline')=='STUDENT_ABILITY_B0':
        return (Step('ability',algorithm='ability_b0'),)
    if batch.configuration.get('pipeline')=='STUDENT_ABILITY':
        return (Step('ability',algorithm='ability'),)
    return STEPS
