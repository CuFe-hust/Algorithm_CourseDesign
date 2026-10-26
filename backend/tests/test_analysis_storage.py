from sqlalchemy import select
from app.analysis.framework.fixtures import demo_snapshot
from app.analysis.framework.snapshots import capture
from app.analysis.framework.contracts import digest
from app.db.models import User
from app.db.models.analytics import AnalysisBatch, AnalysisInputSnapshot


def test_demo_snapshot_is_stable_and_contains_no_live_identity():
    a=demo_snapshot(42)
    assert a==demo_snapshot(42) and a['is_mock']
    assert len(a['roster'])==6 and len(a['answers'])==6
    assert digest(a)==digest(demo_snapshot(42))


def test_real_capture_uses_persisted_course_facts_without_names(db,demo):
    summary,_=demo
    snapshot=capture(db,int(summary['course_id']),None,'REAL_INPUT',42)
    assert not snapshot['is_mock'] and len(snapshot['roster'])==6
    raw=str(snapshot)
    for user in db.scalars(select(User).where(User.student_no.is_not(None))):
        assert user.student_no not in raw and user.full_name not in raw
    assert snapshot['evaluations'] is None and snapshot['grades'] is None


def test_framework_records_roundtrip_without_touching_judge_queue(db,demo):
    summary,_=demo
    teacher=db.scalar(select(User).where(User.login_name=='demo.teacher'))
    batch=AnalysisBatch(course_id=int(summary['course_id']),created_by=teacher.id,mode='DEMO',
        request_id='storage-1',request_hash='a'*64,seed=42,configuration={},events={})
    db.add(batch);db.flush()
    source=AnalysisInputSnapshot(batch_id=batch.id,scope='ROOT',input_hash=digest(demo_snapshot(42)),
        payload=demo_snapshot(42),is_mock=True)
    db.add(source);db.commit()
    assert db.get(AnalysisInputSnapshot,source.id).payload['roster']==demo_snapshot(42)['roster']
