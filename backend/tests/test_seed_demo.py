def test_demo_seed_is_repeatable_and_preserves_versioned_configuration(monkeypatch):
    import secrets
    from sqlalchemy import select, func
    from sqlalchemy.orm import Session
    from app.db.session import make_engine
    from app.db.models import User, AssignmentItem, Problem, ProblemVersion, TestCase, RubricItem
    from app.demo import seed_demo
    monkeypatch.setenv('DB_NAME', 'algorithm_review_test')
    engine = make_engine()
    with Session(engine) as session:
        before = session.scalar(select(func.count()).select_from(User))
        first = seed_demo(session, password=secrets.token_urlsafe(24))
        total = session.scalar(select(func.count()).select_from(User))
        second = seed_demo(session, password=secrets.token_urlsafe(24))
        assert first == second
        assert session.scalar(select(func.count()).select_from(User)) == total
        assert total >= max(before, 7)
        assert {p.question_type for p in session.scalars(select(Problem))} == {'PROGRAMMING','ALGORITHM_ANALYSIS','PROOF','OPEN_QUESTION'}
        assert all(v.status == 'FROZEN' for v in session.scalars(select(ProblemVersion)))
        assert session.scalar(select(func.count()).select_from(TestCase)) >= 5
        assert session.scalar(select(func.count()).select_from(RubricItem)) >= 9
        assert session.scalar(select(func.count()).select_from(AssignmentItem)) == 5
        duplicates = session.execute(select(User.full_name, func.count()).group_by(User.full_name).having(func.count() > 1)).all()
        assert duplicates
    engine.dispose()
