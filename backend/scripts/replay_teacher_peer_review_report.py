"""Synthetic report replay; writes evidence only, never connects to a database."""
import json,time,platform,hashlib,sys,subprocess
from pathlib import Path
from collections import Counter
from decimal import Decimal
from app.analysis.algorithms import review,baseline
from app.analysis.framework.contracts import AllocationInput,AggregationInput,DetectionInput,TimingInput
out=Path(sys.argv[1]);out.mkdir(parents=True,exist_ok=True)
root=Path(review.__file__).resolve().parents[4]
paths=['backend/app/analysis/algorithms/review.py','backend/app/analysis/algorithms/baseline.py','backend/app/analysis/framework/contracts.py']
try:
 baseline_commit=subprocess.check_output(['git','-C',str(root),'rev-parse','HEAD'],stderr=subprocess.DEVNULL,text=True).strip()
except (subprocess.CalledProcessError,FileNotFoundError):
 baseline_commit=None
report={'baseline':baseline_commit,'python':platform.python_version(),'platform':platform.platform(),'is_synthetic':True,'database_used':False,'source_root':str(root),'hashes':{p:hashlib.sha256((root/p).read_bytes()).hexdigest() for p in paths},'runs':[]}
for n in (20,100,217):
 for seed in (20261027,20261110,20261111):
  data=AllocationInput(answers=[dict(answer_key=f'a{i}',author_key=f'u{i}') for i in range(n)],reviewers=[f'u{i}' for i in range(n)],required_reviewers=3,seed=seed)
  for name,fn in [('greedy_baseline',baseline.allocation),('min_cost_flow',review.allocation)]:
   start=time.perf_counter();r=fn(data);seconds=time.perf_counter()-start
   assert r.feasible and len(r.edges)==3*n
   assert Counter(e.answer_key for e in r.edges)=={f'a{i}':3 for i in range(n)}
   assert len({(e.answer_key,e.reviewer_key) for e in r.edges})==3*n
   assert all(e.reviewer_key!='u'+e.answer_key[1:] for e in r.edges)
   loads=list(r.load_metrics.values());report['runs'].append(dict(n=n,seed=seed,method=name,seconds=seconds,tasks=len(r.edges),min_load=min(loads),max_load=max(loads),square_load=sum(v*v for v in loads),constraints_passed=True))
case=AllocationInput(answers=[dict(answer_key='a0',author_key='x0'),dict(answer_key='a1',author_key='x1')],reviewers=['u0','u1'],required_reviewers=1,forbidden_edges=[dict(answer_key='a1',reviewer_key='u1')])
report['greedy_counterexample']={name:fn(case).model_dump(mode='json') for name,fn in [('greedy',baseline.allocation),('flow',review.allocation)]}
assert sum(x*x for x in report['greedy_counterexample']['flow']['load_metrics'].values())==2
assert sum(x*x for x in report['greedy_counterexample']['greedy']['load_metrics'].values())==4
agg=AggregationInput(answers=['a','missing'],evaluations=[dict(evaluation_key=f'e{i}',answer_key='a',score=s,weight=w) for i,(s,w) in enumerate([(60,1),(80,1),(100,'.5')])],rubric_max=100,minimum_samples=2)
report['aggregation']={m:baseline.aggregation(agg.model_copy(update={'method':m})).model_dump(mode='json') for m in ('weighted_mean','weighted_median')}
assert report['aggregation']['weighted_mean']['scores'][0]['normalized_score']=='0.760000'
assert report['aggregation']['weighted_median']['scores'][0]['normalized_score']=='0.800000'
assert report['aggregation']['weighted_mean']['scores'][1]['normalized_score'] is None
es=[dict(evaluation_key=f'e{i}',answer_key='a',reviewer_key=f'u{i}',score=s) for i,s in enumerate([80,80,80,0])]
dev=review.deviation(DetectionInput(evaluations=es,baseline=[],rubric_max=100,minimum_samples=2,threshold='.2'))
assert len(dev.signals)==1 and dev.signals[0].object_key=='e3' and dev.signals[0].value==Decimal('.8')
report['deviation']=dev.model_dump(mode='json')
tm=review.review_timing(TimingInput(timings=[dict(task_key=f't{i}',elapsed_seconds=v) for i,v in enumerate([0,100,100,100,100,None])],minimum_samples=5))
assert tm.missing_count==1 and len(tm.signals)==1 and tm.signals[0].object_key=='t0'
report['timing']=tm.model_dump(mode='json');report['assertions_passed']=True
(out/'replay-results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'runs':len(report['runs']),'assertions_passed':True,'python':report['python']}))
