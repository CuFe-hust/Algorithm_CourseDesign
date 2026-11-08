"""Reproducible synthetic allocation experiment; no DB or credentials."""
import json,platform,time
from collections import Counter
from app.analysis.algorithms.review import allocation
from app.analysis.framework.contracts import AllocationInput
from app.core.config import ROOT


def main():
    rows=[]
    for n in (20,100,217):
        data=AllocationInput(answers=[dict(answer_key=f'a{i}',author_key=f'u{i}') for i in range(n)],
            reviewers=[f'u{i}' for i in range(n)],required_reviewers=3,seed=20261027)
        start=time.perf_counter();result=allocation(data);elapsed=time.perf_counter()-start
        counts=Counter(e.answer_key for e in result.edges)
        assert result.feasible and len(result.edges)==n*3 and set(counts.values())=={3}
        assert len({(e.answer_key,e.reviewer_key) for e in result.edges})==n*3
        assert all(e.reviewer_key!='u'+e.answer_key[1:] for e in result.edges)
        rows.append(dict(participants=n,tasks=len(result.edges),seconds=round(elapsed,4),
            min_load=min(result.load_metrics.values()),max_load=max(result.load_metrics.values()),constraints_passed=True))
    report=dict(algorithm='convex_load_min_cost_flow',version='2',seed=20261027,is_synthetic=True,
        python=platform.python_version(),platform=platform.system()+' '+platform.machine(),runs=rows)
    (ROOT/'data/analysis/review-experiments.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(report,ensure_ascii=False))

if __name__=='__main__':main()
