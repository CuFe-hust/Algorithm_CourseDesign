"""Versioned D1 task input enrichment; no live reconstruction of formal evidence."""
import json
from app.core.config import ROOT
from .difficulty_contracts import DifficultyInputV1, ModelParameters
from .contracts import digest


def selected_parameters():
    path=ROOT/'data/analysis/experiments/difficulty-v1/selected-parameters.json'
    return ModelParameters.model_validate(json.loads(path.read_text(encoding='utf-8'))) if path.exists() else ModelParameters()


def enrich(data,mode):
    if data['learning_input'] is None:return data
    learning=data['learning_input']
    processes=[]
    if mode=='DEMO':
        # Match the B0 fixture's scored records, enriching only the question difficulty metadata.
        questions=[]
        for name in ('questions.programming.json','questions.subjective.json'):
            questions+=json.loads((ROOT/'data/formatted'/name).read_text(encoding='utf-8'))
        metadata={q['code']:q for q in questions}
        for item in learning['items']:
            item['difficulty']=metadata[item['item_code']]['difficulty']
        programming={i['item_key'] for i in learning['items'] if i['item_type']=='PROGRAMMING'}
        for grade in learning['grades']:
            if grade['item_key'] not in programming:continue
            score=float(grade['normalized_score'])
            for seq,verdict,value in [(1,'CE',None),(2,'WA',str(score/2)),
                                      (3,'AC' if score==1 else 'WA',grade['normalized_score'])]:
                processes.append(dict(student_key=grade['student_key'],item_key=grade['item_key'],
                    sequence_no=seq,verdict=verdict,score=value))
    wrapped=DifficultyInputV1(learning_input=learning,model_parameters=selected_parameters(),processes=processes)
    payload=wrapped.model_dump(mode='json')
    return dict(data,learning_input=payload,source=dict(data['source'],model='DIFFICULTY_FRACTIONAL',
        model_parameter_hash=digest(payload['model_parameters']),
        process_evidence='SYNTHETIC_TRAJECTORY' if processes else 'UNAVAILABLE'))
