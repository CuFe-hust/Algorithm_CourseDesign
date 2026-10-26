"""Export schemas and synthetic examples. No database or credentials are read."""
import json
from app.core.config import ROOT
from app.analysis.framework.catalog import catalogue,invoke
from app.analysis.framework.contracts import digest
from app.analysis.framework.fixtures import demo_snapshot
from app.analysis.framework.graph import STEPS
from app.analysis.framework.payloads import prepare,rule_output,human_output,NotApplicable


def build_examples():
    root=demo_snapshot(20261026);outputs={};examples={}
    for step in STEPS:
        if step.key=='collect_supplement':continue
        if step.event:
            outputs[step.key]={'payload':human_output(step.key,root,outputs)};continue
        try:payload=prepare(step.key,root,outputs)
        except NotApplicable:continue
        if step.algorithm:
            result=invoke(step.algorithm,payload,mode='DEMO',seed=20261026,input_hash=digest(payload)).model_dump(mode='json')
            if step.algorithm not in examples:
                examples[step.algorithm]={'input':dict(schema_version='analysis-v1',algorithm_key=step.algorithm,
                    snapshot_id=f'synthetic-{step.key}',input_hash=digest(payload),parameters={},seed=20261026,payload=payload),
                    'output':result}
        else:result={'payload':rule_output(step.key,payload,root)}
        outputs[step.key]=result
    return examples


def write(path,value):
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8',newline='\n')


def main():
    directory=ROOT/'data/analysis';directory.mkdir(parents=True,exist_ok=True)
    examples=build_examples()
    write(directory/'catalog.json',{'schema_version':'analysis-v1','items':catalogue()})
    write(directory/'example-inputs.json',{k:v['input'] for k,v in examples.items()})
    write(directory/'example-outputs.json',{k:v['output'] for k,v in examples.items()})
    print(json.dumps({'plugins':len(examples),'privacy':'synthetic-only','database_used':False}))


if __name__=='__main__':main()
