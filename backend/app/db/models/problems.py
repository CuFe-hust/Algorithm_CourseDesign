from datetime import datetime
from decimal import Decimal
from sqlalchemy import ForeignKey, String, Text, UniqueConstraint, CheckConstraint, JSON
from sqlalchemy.dialects.mysql import BIGINT, DATETIME, LONGTEXT, INTEGER, TINYINT
from sqlalchemy import Numeric
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base, Mutable


class Problem(Mutable, Base):
    __tablename__ = 'problems'
    course_id: Mapped[int] = mapped_column(BIGINT(unsigned=True), ForeignKey('courses.id'))
    code: Mapped[str] = mapped_column(String(32))
    question_type: Mapped[str] = mapped_column(String(32))
    created_by: Mapped[int] = mapped_column(BIGINT(unsigned=True), ForeignKey('users.id'))
    status: Mapped[str] = mapped_column(String(16), default='ACTIVE')
    __table_args__ = (UniqueConstraint('course_id', 'code'), CheckConstraint(
        "question_type IN ('PROGRAMMING','ALGORITHM_ANALYSIS','PROOF','OPEN_QUESTION')", name='ck_problem_type'))


class ProblemVersion(Mutable, Base):
    __tablename__ = 'problem_versions'
    problem_id: Mapped[int] = mapped_column(BIGINT(unsigned=True), ForeignKey('problems.id'))
    version_no: Mapped[int] = mapped_column(INTEGER(unsigned=True))
    title: Mapped[str] = mapped_column(String(200))
    statement_md: Mapped[str] = mapped_column(LONGTEXT)
    answer_requirements_md: Mapped[str | None] = mapped_column(Text)
    input_spec_md: Mapped[str | None] = mapped_column(Text)
    output_spec_md: Mapped[str | None] = mapped_column(Text)
    data_constraints_md: Mapped[str | None] = mapped_column(Text)
    public_examples_md: Mapped[str | None] = mapped_column(Text)
    difficulty_level: Mapped[int] = mapped_column(TINYINT(unsigned=True))
    source_reference: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int] = mapped_column(BIGINT(unsigned=True), ForeignKey('users.id'))
    status: Mapped[str] = mapped_column(String(16), default='DRAFT')
    frozen_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6))
    __table_args__ = (UniqueConstraint('problem_id', 'version_no'),
        CheckConstraint('difficulty_level BETWEEN 1 AND 5', name='ck_problem_difficulty'),
        CheckConstraint('version_no > 0', name='ck_problem_version_positive'),
        CheckConstraint("(status='DRAFT' AND frozen_at IS NULL) OR (status='FROZEN' AND frozen_at IS NOT NULL)", name='ck_problem_frozen'))


class KnowledgePoint(Mutable, Base):
    __tablename__ = 'knowledge_points'
    course_id: Mapped[int] = mapped_column(BIGINT(unsigned=True), ForeignKey('courses.id'))
    code: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(16), default='ACTIVE')
    __table_args__ = (UniqueConstraint('course_id', 'code'),)


class ProblemVersionTag(Base):
    __tablename__ = 'problem_version_tags'
    problem_version_id: Mapped[int] = mapped_column(BIGINT(unsigned=True), ForeignKey('problem_versions.id'))
    knowledge_point_id: Mapped[int] = mapped_column(BIGINT(unsigned=True), ForeignKey('knowledge_points.id'))
    mastery_weight: Mapped[Decimal] = mapped_column(Numeric(8, 6))
    __table_args__ = (UniqueConstraint('problem_version_id', 'knowledge_point_id'),
        CheckConstraint('mastery_weight > 0 AND mastery_weight <= 1', name='ck_tag_weight'))


class TestSuite(Base):
    __tablename__ = 'test_suites'
    problem_version_id: Mapped[int] = mapped_column(BIGINT(unsigned=True), ForeignKey('problem_versions.id'))
    version_no: Mapped[int] = mapped_column(INTEGER(unsigned=True))
    cpu_limit_ms: Mapped[int] = mapped_column(INTEGER(unsigned=True))
    memory_limit_kib: Mapped[int] = mapped_column(INTEGER(unsigned=True))
    allowed_languages: Mapped[list] = mapped_column(JSON)
    checker: Mapped[str] = mapped_column(String(32), default='TEXT_TRIM_TRAILING')
    status: Mapped[str] = mapped_column(String(16), default='FROZEN')
    frozen_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6))
    __table_args__ = (UniqueConstraint('problem_version_id', 'version_no'),
        CheckConstraint('cpu_limit_ms > 0 AND memory_limit_kib > 0', name='ck_suite_resources'),
        CheckConstraint('version_no > 0', name='ck_suite_version_positive'),
        CheckConstraint("status='FROZEN'", name='ck_suite_frozen'))


class TestCase(Base):
    __tablename__ = 'test_cases'
    test_suite_id: Mapped[int] = mapped_column(BIGINT(unsigned=True), ForeignKey('test_suites.id'))
    sort_order: Mapped[int] = mapped_column(INTEGER(unsigned=True))
    input_text: Mapped[str] = mapped_column(LONGTEXT)
    expected_output: Mapped[str] = mapped_column(LONGTEXT)
    weight: Mapped[Decimal] = mapped_column(Numeric(8, 6))
    is_public: Mapped[bool]
    __table_args__ = (UniqueConstraint('test_suite_id', 'sort_order'),
        CheckConstraint('weight > 0 AND weight <= 1', name='ck_case_weight'))


class ReferenceSolution(Base):
    __tablename__ = 'reference_solutions'
    problem_version_id: Mapped[int] = mapped_column(BIGINT(unsigned=True), ForeignKey('problem_versions.id'), index=True)
    language: Mapped[str | None] = mapped_column(String(32))
    content: Mapped[str] = mapped_column(LONGTEXT)
    created_by: Mapped[int] = mapped_column(BIGINT(unsigned=True), ForeignKey('users.id'))


class Rubric(Base):
    __tablename__ = 'rubrics'
    problem_version_id: Mapped[int] = mapped_column(BIGINT(unsigned=True), ForeignKey('problem_versions.id'))
    version_no: Mapped[int] = mapped_column(INTEGER(unsigned=True))
    name: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(16), default='FROZEN')
    frozen_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6))
    __table_args__ = (UniqueConstraint('problem_version_id', 'version_no'),
        CheckConstraint("status='FROZEN'", name='ck_rubric_frozen'))


class RubricItem(Base):
    __tablename__ = 'rubric_items'
    rubric_id: Mapped[int] = mapped_column(BIGINT(unsigned=True), ForeignKey('rubrics.id'))
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(Text)
    max_score: Mapped[Decimal] = mapped_column(Numeric(8, 2))
    sort_order: Mapped[int] = mapped_column(INTEGER(unsigned=True))
    __table_args__ = (UniqueConstraint('rubric_id', 'sort_order'),
        CheckConstraint('max_score > 0', name='ck_rubric_score'))
