"""Wholly synthetic, stable data. Never reads the live course roster."""
import random

# Synthetic submissions written to exercise the real similarity algorithm in
# DEMO mode. They solve no real problem and belong to no real student; they exist
# so the demo contract shows pairs, matched ranges and a cluster instead of an
# empty payload. Four are cosmetic variants of one another, two are unrelated.
_CODE_TEMPLATES = (
    """n = int(input())
items = [tuple(map(int, input().split())) for _ in range(n)]
last, taken = -1, 0
for begin, end in sorted(items, key=lambda pair: (pair[1], pair[0])):
    if begin >= last:
        last, taken = end, taken + 1
print(taken)
""",
    """count = int(input())
rows = [tuple(map(int, input().split())) for _ in range(count)]
boundary = -1
answer = 0
for start, finish in sorted(rows, key=lambda item: (item[1], item[0])):
    if start >= boundary:
        boundary, answer = finish, answer + 1
print(answer)
""",
    """count = int(input())
intervals = [tuple(map(int, input().split())) for _ in range(count)]
finish_of_last = -1
picked = 0
for begin, end in sorted(intervals, key=lambda item: (item[1], item[0])):
    if begin >= finish_of_last:
        finish_of_last, picked = end, picked + 1
print(picked)
""",
    """# 贪心：按结束时间排序，依次接纳不冲突的活动
n = int(input())
intervals = [tuple(map(int, input().split())) for _ in range(n)]
last_end = -1
taken = 0
for start_time, end_time in sorted(intervals, key=lambda pair: (pair[1], pair[0])):
    if start_time >= last_end:
        last_end, taken = end_time, taken + 1
print(taken)
""",
    """total = 0
for value in map(int, input().split()):
    total ^= value
print(total)
""",
    """n = int(input())
best = 0
for _ in range(n):
    first, second = map(int, input().split())
    best = max(best, abs(second - first))
print(best)
""",
)


def demo_snapshot(seed):
    rng=random.Random(seed)
    roster=[f'demo-u{i}' for i in range(1,7)]
    answers=[dict(answer_key=f'a{i}',author_key=u,content=f'Synthetic proof {i}: induction.',language=None)
             for i,u in enumerate(roster,1)]
    code=[dict(answer_key=f'c{i}',author_key=u,content=_CODE_TEMPLATES[i-1],language='python3')
          for i,u in enumerate(roster,1)]
    return dict(schema_version='analysis-v2',is_mock=True,roster=roster,reviewers=roster,answers=answers,code=code,
        rubric_max='100',required_reviewers=2,reference_scores={a['answer_key']:rng.randint(50,95) for a in answers},
        judge_results=[dict(student_key=u,submission_key=f'demo-code-{i}',passed_cases=3+i%3,total_cases=5,
            verdict='ACCEPTED' if i%3==2 else 'WRONG_ANSWER',execution_mode='MOCK',runtime_profile='analysis-demo-v1',is_mock=True)
            for i,u in enumerate(roster)],evaluations=None,grades=None,
        events=[dict(student_key=u,kind='SUBMITTED',occurred_at='2026-10-26T08:00:00+00:00') for u in roster],
        available_event_types=['SUBMITTED'],time_range={'from':'2026-10-26T00:00:00Z','to':'2026-10-27T00:00:00Z'},
        test_suite_key='demo-suite',evaluation_context={'execution_mode':'MOCK','runtime_profile':'analysis-demo-v1'},
        submitted=roster,source_versions={'fixture':'synthetic-six-v2'})
