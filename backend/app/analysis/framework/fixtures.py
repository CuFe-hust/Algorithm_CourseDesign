"""Wholly synthetic, stable data. Never reads the live course roster."""
import random


def demo_snapshot(seed):
    rng=random.Random(seed)
    roster=[f'demo-u{i}' for i in range(1,7)]
    answers=[dict(answer_key=f'a{i}',author_key=u,content=f'Synthetic proof {i}: induction.',language=None)
             for i,u in enumerate(roster,1)]
    code=[dict(answer_key=f'c{i}',author_key=u,content=f'print({i})',language='python3') for i,u in enumerate(roster,1)]
    return dict(schema_version='analysis-v1',is_mock=True,roster=roster,reviewers=roster,answers=answers,code=code,
        rubric_max='100',required_reviewers=2,reference_scores={a['answer_key']:rng.randint(50,95) for a in answers},
        judge_results=[dict(student_key=u,submission_key=f'demo-code-{i}',passed_cases=3+i%3,total_cases=5,
            verdict='ACCEPTED' if i%3==2 else 'WRONG_ANSWER',execution_mode='MOCK',runtime_profile='analysis-demo-v1',is_mock=True)
            for i,u in enumerate(roster)],evaluations=None,grades=None,
        events=[dict(student_key=u,kind='SUBMITTED',occurred_at='2026-10-26T08:00:00+00:00') for u in roster],
        available_event_types=['SUBMITTED'],time_range={'from':'2026-10-26T00:00:00Z','to':'2026-10-27T00:00:00Z'},
        test_suite_key='demo-suite',evaluation_context={'execution_mode':'MOCK','runtime_profile':'analysis-demo-v1'},
        submitted=roster,source_versions={'fixture':'synthetic-six-v1'})
