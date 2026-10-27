from app.analysis.framework.graph import STEPS
from app.db.models import AssignmentItem
from app.teacher.schemas import AssignmentItemInput


def test_assignment_has_no_cross_question_score_weight():
    assert 'score_weight' not in AssignmentItem.__table__.columns
    assert 'score_weight' not in AssignmentItemInput.model_fields


def test_learning_depends_on_question_results_without_total_or_release():
    graph={s.key:s for s in STEPS}
    assert 'total_scores' not in graph and 'release' not in graph
    assert graph['result_snapshot'].dependencies==('item_scores',)
    for key in ('mastery','ability','statistics','empirical_difficulty'):
        assert graph[key].dependencies==('result_snapshot',)


def test_migration_fences_legacy_batches_without_deleting_history(db,demo):
    from pathlib import Path
    import pytest
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import select
    from app.db.models import User
    from app.db.models.analytics import AnalysisBatch,AnalysisRun
    from app.analysis.framework.service import create_batch,batch_view
    from app.core.errors import AppError
    actor=db.scalar(select(User).where(User.login_name=='demo.teacher'))
    view=create_batch(db,int(demo[0]['course_id']),actor,dict(mode='DEMO',seed=42,
        request_id='legacy-case',assignment_id=None,assignment_item_id=None))
    bid=int(view['id']);batch=db.get(AnalysisBatch,bid)
    batch.configuration={'schema_version':'analysis-v1'};db.commit()
    import os
    previous=os.environ.get('DB_NAME');os.environ['DB_NAME']='algorithm_review_test'
    try:
        config=Config(str(Path(__file__).resolve().parents[1]/'alembic.ini'))
        command.downgrade(config,'pg0005');command.upgrade(config,'head')
    finally:
        if previous is None:os.environ.pop('DB_NAME',None)
        else:os.environ['DB_NAME']=previous
    db.expire_all()
    assert db.get(AnalysisBatch,bid).status=='CANCELLED'
    assert len(list(db.scalars(select(AnalysisRun).where(AnalysisRun.batch_id==bid))))==23
    assert all(r.status=='CANCELLED' for r in db.scalars(select(AnalysisRun).where(AnalysisRun.batch_id==bid)))
    with pytest.raises(AppError) as error:batch_view(db,bid,actor)
    assert error.value.code=='ANALYSIS_BATCH_SCHEMA_OUTDATED'
