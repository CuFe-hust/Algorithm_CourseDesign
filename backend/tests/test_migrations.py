def test_mysql_schema_has_complete_foreign_keys_and_repeatable_upgrade(monkeypatch):
    from pathlib import Path
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import inspect, text
    from app.db.base import Base
    from app.db import models
    from app.db.session import make_engine
    monkeypatch.setenv('DB_NAME', 'algorithm_review_test')
    engine = make_engine()
    required = {'users', 'classes', 'student_profiles', 'courses', 'course_members', 'problems',
                'problem_versions', 'knowledge_points', 'problem_version_tags', 'assignments',
                'assignment_items', 'assignment_participants', 'submissions', 'test_suites',
                'test_cases', 'reference_solutions', 'rubrics', 'rubric_items', 'analysis_jobs',
                'judge_results', 'auth_sessions'}
    try:
        config = Config(str(Path(__file__).resolve().parents[1] / 'alembic.ini'))
        assert engine.url.database == 'algorithm_review_test'
        assert set(inspect(engine).get_table_names()) <= required | {'alembic_version'}
        Base.metadata.drop_all(engine)
        with engine.begin() as connection:
            connection.execute(text('DROP TABLE IF EXISTS alembic_version'))
        command.upgrade(config, 'head')
        command.upgrade(config, 'head')
        assert required <= set(inspect(engine).get_table_names())
        assert len(inspect(engine).get_foreign_keys('assignment_items')) == 4
    finally:
        engine.dispose()
