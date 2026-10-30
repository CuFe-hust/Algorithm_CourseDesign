"""Real HTTP/CLI worker smoke restricted to localhost and synthetic DEMO_ALGO."""
import argparse,json,subprocess,sys,time,uuid
from datetime import datetime,timedelta,timezone
from decimal import Decimal
from pathlib import Path
import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.config import ROOT
from app.db.session import make_engine
from app.db.models import Course,User,AssignmentItem,ProblemVersion,Problem


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--credentials',type=Path,required=True);parser.add_argument('--prepare-ui',action='store_true');parser.add_argument('--with-programming',action='store_true')
    args=parser.parse_args();password=json.loads(args.credentials.read_text())['password']
    client=httpx.Client(base_url='http://127.0.0.1:8000/api/v1',timeout=30,trust_env=False)
    def call(method,path,headers=None,data=None):
        r=client.request(method,path,headers=headers,json=data)
        if not r.is_success:raise AssertionError(f'{method} {path}: {r.status_code} {r.text}')
        return r.json()
    def login(name):return {'Authorization':'Bearer '+call('POST','/auth/login',data=dict(login_name=name,password=password))['access_token']}
    teacher=login('demo.teacher')
    with Session(make_engine()) as db:
        course=db.scalar(select(Course).where(Course.code=='DEMO_ALGO'));assert course and '合成演示' in course.name
        students=list(db.scalars(select(User).where(User.login_name.like('demo.student%')).order_by(User.id)))
        item=db.scalar(select(AssignmentItem).join(ProblemVersion,ProblemVersion.id==AssignmentItem.problem_version_id)
            .join(Problem,Problem.id==ProblemVersion.problem_id).where(Problem.course_id==course.id,AssignmentItem.rubric_id.is_not(None)))
        config=dict(problem_version_id=str(item.problem_version_id),rubric_id=str(item.rubric_id),max_score='20',required_reviewers=2 if args.prepare_ui else 3)
        programming=db.scalar(select(AssignmentItem).join(ProblemVersion,ProblemVersion.id==AssignmentItem.problem_version_id).join(Problem,Problem.id==ProblemVersion.problem_id).where(Problem.course_id==course.id,AssignmentItem.test_suite_id.is_not(None)))
        program_config=dict(problem_version_id=str(programming.problem_version_id),test_suite_id=str(programming.test_suite_id),max_score='100',required_reviewers=0)
        course_id=str(course.id);users=[(str(u.id),u.login_name) for u in students]
    headers={uid:login(name) for uid,name in users}
    now=lambda:datetime.now(timezone.utc)
    rid=lambda:uuid.uuid4().hex
    a=call('POST',f'/teacher/courses/{course_id}/assignments',teacher,dict(title='合成联调：'+('页面互评验收' if args.prepare_ui else '主观互评全链路')+' '+now().strftime('%H%M%S'),
        submission_deadline=(now()+timedelta(days=1)).isoformat(),review_deadline=(now()+timedelta(days=3)).isoformat(),items=[config,*([program_config] if args.with_programming else [])],student_ids=[uid for uid,_ in users]))
    a=call('POST',f"/teacher/assignments/{a['id']}/publish",teacher,dict(expected_updated_at=a['updated_at'],submission_status='OPEN'))
    item_id=a['items'][0]['id']
    for index,(uid,_) in enumerate(users):
        call('POST',f'/assignment-items/{item_id}/submissions',headers[uid],dict(content=f'合成作品 {index+1}：\n\n令搜索区间为 [l,r)，初始 l=0,r=n。取 m=(l+r)//2；若 a[m]<target 则 l=m+1，否则 r=m。\n\n不变量：所有 i<l 满足 a[i]<target，所有 i>=r 满足 a[i]>=target。每步区间缩短，终止时 l=r 即左边界。空数组返回0，目标大于最大值返回n；时间 O(log n)，额外空间 O(1)。',client_request_id=rid()))
    programming_submissions=[]
    if args.with_programming:
        program_item=a['items'][1]['id']
        code="n=int(input())\nintervals=[tuple(map(int,input().split())) for _ in range(n)]\nlast=-1\nanswer=0\nfor start,end in sorted(intervals,key=lambda x:(x[1],x[0])):\n    if start>=last:\n        last=end\n        answer+=1\nprint(answer)\n"
        for uid,_ in users:
            receipt=call('POST',f'/assignment-items/{program_item}/submissions',headers[uid],dict(content=code,language='python3',client_request_id=rid()))
            programming_submissions.append(receipt['submission_id'])
        for _ in range(120):
            details=[call('GET',f'/submissions/{sid}',teacher) for sid in programming_submissions]
            if all(d.get('result') and d['result']['verdict']=='ACCEPTED' and not d['result']['is_mock'] for d in details):break
            time.sleep(.25)
        else:raise AssertionError('Local judge did not accept six synthetic programs')
    cutoff=now();time.sleep(.02)
    a=call('POST',f"/teacher/assignments/{a['id']}/schedule",teacher,dict(expected_updated_at=a['updated_at'],submission_status='CLOSED',submission_deadline=cutoff.isoformat(),review_deadline=(now()+timedelta(days=3)).isoformat()))
    out=ROOT/'local-data/peer-review-qa';out.mkdir(exist_ok=True)
    if args.prepare_ui:
        report=dict(course_id=course_id,assignment_id=a['id'],assignment_item_id=item_id,student_login='demo.student01')
        (out/'ui-scope.json').write_text(json.dumps(report,indent=2));print(json.dumps(report));return
    def worker():subprocess.run([sys.executable,'-m','scripts.run_analysis','--limit','100'],cwd=ROOT/'backend',check=True,capture_output=True)
    def view(round_id):return call('GET',f'/peer-review/teacher/rounds/{round_id}',teacher)
    def publish(r):
        worker();r=view(r['id']);assert r['allocation']['business_status']=='OK'
        return call('POST',f"/peer-review/teacher/rounds/{r['id']}/publish",teacher,dict(request_id=rid(),expected_revision=r['revision'],expected_source_hash=r['source_hash']))
    def score_round(round_id):
        tasks=call('GET',f'/peer-review/teacher/rounds/{round_id}/tasks?limit=100',teacher)['items']
        for t in tasks:
            sh=headers[t['reviewer_id']];v=call('GET',f"/peer-review/tasks/{t['task_id']}",sh)
            assert not {'author_key','reviewer_id','submission_id','student_id'}&v.keys()
            payload=dict(client_request_id=rid(),scores=[dict(rubric_item_id=d['id'],score=str(Decimal(d['max_score'])*Decimal('.8'))) for d in v['rubric']],comment='半开区间、不变量与终止性说明清晰；建议用重复元素和空数组示例补充边界验证。')
            response=call('POST',f"/peer-review/tasks/{t['task_id']}/evaluation",sh,payload)
            assert response['evaluation'] and call('POST',f"/peer-review/tasks/{t['task_id']}/evaluation",sh,payload)['replayed']
        return call('GET',f'/peer-review/teacher/rounds/{round_id}/tasks?limit=100',teacher)['items']
    def close(r):
        r=view(r['id']);call('POST',f"/peer-review/teacher/rounds/{r['id']}/close",teacher,dict(request_id=rid(),expected_revision=r['revision'],reason='合成真实HTTP：完成任务后封存'))
        worker();return view(r['id'])
    def resolve(r,decisions,supplement=False):
        a=r['latest_analysis'];statuses={s['key']:s['business_status'] for s in a['runs'] if s['key'] in ('deviation','reviewer_bias','review_timing','relationship')}
        payload=dict(request_id=rid(),expected_revision=r['root_revision'],expected_source_hash=a['source_hash'],reason='合成验收：逐项检查证据覆盖，保留独立人工决定',acknowledged_statuses=statuses,decisions=decisions,request_supplement=supplement)
        if supplement:payload['supplement_deadline']=(now()+timedelta(days=3)).isoformat()
        call('POST',f"/peer-review/teacher/analyses/{a['id']}/resolve",teacher,payload);worker();return view(r['root_round_id'])
    r=call('POST',f'/peer-review/teacher/assignment-items/{item_id}/previews',teacher,dict(request_id=rid(),review_deadline=(now()+timedelta(days=2)).isoformat()))
    r=publish(r);tasks=score_round(r['id']);r=close(r)
    t=tasks[0];original=call('GET',f"/peer-review/teacher/tasks/{t['task_id']}",teacher)['evaluation']
    r=resolve(r,[dict(action='INVALIDATE',evaluation_id=t['evaluation_id'],reason='合成复核：验证作废与补评流程')],True)
    child=next(x for x in r['rounds'] if x['round_no']>1)
    extra=publish(view(child['id']));new_tasks=score_round(extra['id'])
    assert len(new_tasks)==1 and not {(t['answer_key'],t['reviewer_id']) for t in tasks}&{(t['answer_key'],t['reviewer_id']) for t in new_tasks}
    r=close(extra);r=resolve(r,[dict(action='OVERRIDE',answer_key=t['answer_key'],override_score='17.50',reason='合成教师独立改分，保留原始评价')])
    result=call('GET',f"/peer-review/teacher/rounds/{r['id']}/results",teacher)
    assert result['status']=='READY' and result['version']==3
    assert call('GET',f"/peer-review/teacher/tasks/{t['task_id']}",teacher)['evaluation']==original
    assert all(x['item_score'] is not None for x in result['rows'])
    report=dict(is_synthetic=True,transport='real HTTP / localhost',worker='separate CLI process',course_id=course_id,assignment_id=a['id'],root_round_id=r['id'],rounds=len(r['rounds']),original_tasks=len(tasks),supplement_tasks=len(new_tasks),analysis_versions=len(r['analyses']),candidate_version=result['version'],candidate_count=len(result['rows']),raw_evaluation_unchanged=True,no_mock_algorithm_outputs=not result['is_mock'],supplement_no_repeated_pairs=True)
    if args.with_programming:
        snapshot=call('POST',f'/analysis/courses/{course_id}/question-results',teacher,dict(request_id=rid(),assignment_id=a['id'],reason='整合验收：真实编程评测与主观复核共同形成逐题快照'))
        assert snapshot['known_count']==12 and snapshot['missing_count']==0
        assert {row['source']['kind'] for row in snapshot['rows']}=={'JUDGE_RESULT','REVIEW_ANALYSIS'}
        personal=call('GET',f"/analysis/question-results/{snapshot['id']}",headers[users[0][0]])
        assert personal['total']==2 and all('student_id' not in row and 'student_name' not in row for row in personal['rows'])
        report.update(programming_real_accepted=len(programming_submissions),question_results_id=snapshot['id'],known_question_samples=snapshot['known_count'],personal_projection_verified=True)
        (out/'platform-http-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    (out/'http-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));print(json.dumps(report,ensure_ascii=False))

if __name__=='__main__':main()
