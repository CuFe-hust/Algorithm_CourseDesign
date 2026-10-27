"""Dependency adapters. Only this layer knows how artifacts connect."""
from decimal import Decimal
from .contracts import digest


class MissingInput(Exception):pass
class NotApplicable(Exception):pass


def body(outputs,key):
    return outputs.get(key,{}).get('payload',{})


def prepare(key,root,outputs):
    if key=='judge_adapter':
        return dict(results=root['judge_results'],test_suite_key=root['test_suite_key'],evaluation_context=root['evaluation_context'])
    if key=='behavior':
        return {k:root[k] for k in ('events','available_event_types','time_range')}
    if key in ('code_similarity','text_similarity','ai_signal'):
        source=root['code'] if key=='code_similarity' else root['answers']
        if not source:raise MissingInput('NO_SUBMISSION_SNAPSHOT')
        item_keys={a.get('item_key') for a in source}
        if len(item_keys)>1:raise MissingInput('SINGLE_ITEM_SCOPE_REQUIRED')
        if not root['is_mock'] and not all(s['closed'] for s in root.get('scopes',[]) if s['item_key'] in item_keys):
            raise MissingInput('SOURCE_NOT_FROZEN_CREATE_NEW_BATCH_AFTER_CLOSE')
        return dict(answers=[{k:a[k] for k in ('answer_key','content','language')} for a in source],
            templates=[],comparison_scope='SAME_ITEM')
    if key in ('allocation','supplement_allocation'):
        if not root['answers']:raise MissingInput('NO_SUBJECTIVE_ANSWERS')
        if not root['is_mock']:
            if root.get('required_reviewers') is None:raise MissingInput('SINGLE_SUBJECTIVE_ITEM_SCOPE_REQUIRED')
            if not all(s['closed'] for s in root.get('scopes',[])):raise MissingInput('SOURCE_NOT_FROZEN_CREATE_NEW_BATCH_AFTER_CLOSE')
        answers=[{k:a[k] for k in ('answer_key','author_key')} for a in root['answers']]
        existing=[];k=root['required_reviewers']
        if key=='supplement_allocation':
            if body(outputs,'resolve').get('action')!='SUPPLEMENT':raise NotApplicable('NO_SUPPLEMENT_REQUIRED')
            # Demo removes one evaluation per answer and requests one new reviewer.
            existing=body(outputs,'allocation')['edges'];k=1
        return dict(answers=answers,reviewers=root['reviewers'],required_reviewers=k,
            forbidden_edges=[],existing_edges=existing,history=[])
    if key in ('aggregation','reaggregation'):
        if root['rubric_max'] is None:raise MissingInput('RUBRIC_SNAPSHOT_REQUIRED')
        evaluations=list(body(outputs,'collect_reviews').get('evaluations',[]))
        if not evaluations:raise MissingInput('RAW_EVALUATIONS_REQUIRED')
        if key=='reaggregation' and body(outputs,'resolve').get('action')=='SUPPLEMENT':
            removed=set(body(outputs,'resolve')['invalidated_evaluations'])
            evaluations=[dict(e,weight='0') if e['evaluation_key'] in removed else e for e in evaluations]
            evaluations+=body(outputs,'collect_supplement').get('evaluations',[])
        return dict(answers=[a['answer_key'] for a in root['answers']],rubric_max=root['rubric_max'],
            minimum_samples=2,evaluations=evaluations)
    if key in ('deviation','reviewer_bias','relationship'):
        return dict(evaluations=body(outputs,'collect_reviews')['evaluations'],baseline=body(outputs,'aggregation')['scores'],
            history=[],edges=body(outputs,'allocation')['edges'],minimum_samples=2,threshold='0.2')
    if key=='review_timing':
        return dict(timings=body(outputs,'collect_reviews')['timings'],minimum_samples=2)
    if key in ('mastery','ability','empirical_difficulty','statistics'):
        snapshot=body(outputs,'result_snapshot')
        if 'grades' not in snapshot:raise MissingInput('QUESTION_RESULTS_SNAPSHOT_REQUIRED')
        data=dict(grades=snapshot['grades'],results_snapshot_version=snapshot['results_snapshot_version'])
        if key=='statistics':return dict(data,roster=root['roster'],submitted=root['submitted'])
        return dict(data,minimum_samples=2)
    if key=='item_scores':
        if not root['is_mock']:raise MissingInput('FORMAL_SCORE_POLICY_AND_EVIDENCE_REQUIRED')
        return dict(subjective_scores=body(outputs,'reaggregation')['scores'],judge_results=root['judge_results'])
    if key=='result_snapshot':return dict(grades=body(outputs,'item_scores')['grades'])
    raise MissingInput('NO_ADAPTER_INSTALLED')


def rule_output(key,payload,root):
    if key=='item_scores':
        authors={a['answer_key']:a['author_key'] for a in root['answers']};grades=[]
        for score in payload['subjective_scores']:
            if score['normalized_score'] is None:raise MissingInput('SUBJECTIVE_SCORE_UNAVAILABLE')
            grades.append(dict(student_key=authors[score['answer_key']],item_key='demo-subjective',
                normalized_score=score['normalized_score'],knowledge_weights={'algorithm':'1'},difficulty=3))
        for result in payload['judge_results']:
            grades.append(dict(student_key=result['student_key'],item_key='demo-programming',
                normalized_score=str(Decimal(result['passed_cases'])/result['total_cases']),
                knowledge_weights={'algorithm':'1'},difficulty=3))
        return dict(grades=grades,policy='DEMO_EQUAL_CASES_ONLY')
    if key=='result_snapshot':
        return dict(grades=payload['grades'],results_snapshot_version='question-results-'+digest(payload['grades'])[:16])
    raise ValueError('Unknown rule step')


def human_output(key,root,outputs,action='KEEP'):
    if key=='open_review':return dict(opened=True,synthetic=True)
    if key in ('collect_reviews','collect_supplement'):
        edge_key='allocation' if key=='collect_reviews' else 'supplement_allocation'
        edges=body(outputs,edge_key)['edges'];evaluations=[];timings=[]
        for i,edge in enumerate(edges):
            score=root['reference_scores'][edge['answer_key']]
            ek=f'{key}-{i}'
            evaluations.append(dict(evaluation_key=ek,answer_key=edge['answer_key'],reviewer_key=edge['reviewer_key'],
                score=str(max(0,min(100,score+i%5-2))),weight='1'))
            timings.append(dict(task_key=ek,elapsed_seconds=str(60+i)))
        return dict(evaluations=evaluations,timings=timings,synthetic=True)
    if key=='resolve':
        removed=[];seen=set()
        if action=='SUPPLEMENT':
            for e in body(outputs,'collect_reviews')['evaluations']:
                if e['answer_key'] not in seen:removed.append(e['evaluation_key']);seen.add(e['answer_key'])
        return dict(action=action,invalidated_evaluations=removed,synthetic=True,
            reason='Synthetic meeting demonstration; no real student decision.')
    raise ValueError('Unsupported human step')
