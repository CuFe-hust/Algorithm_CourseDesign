"""Teacher inputs reuse the shared schema; no teacher-only copy of business tables."""
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

MAX_ID = 9223372036854775807
DbId = Annotated[int, Field(gt=0, le=MAX_ID)]
QuestionType = Literal['PROGRAMMING', 'ALGORITHM_ANALYSIS', 'PROOF', 'OPEN_QUESTION']
Weight = Annotated[Decimal, Field(gt=0, le=1, max_digits=8, decimal_places=6)]


class Input(BaseModel):
    model_config = ConfigDict(extra='forbid')

    @field_validator('*', mode='before')
    @classmethod
    def reject_nul(cls, value):
        if isinstance(value, str) and '\x00' in value:
            raise ValueError('Text cannot contain NUL.')
        return value


class ReferenceInput(Input):
    language: str | None = Field(default=None, max_length=32)
    content: str = Field(min_length=1, max_length=262144)


class CaseInput(Input):
    input_text: str = Field(default='', max_length=262144)
    expected_output: str = Field(default='', max_length=262144)
    weight: Weight = Decimal('1')
    is_public: bool = False


class SuiteInput(Input):
    cpu_limit_ms: int = Field(default=1000, ge=100, le=30000)
    memory_limit_kib: int = Field(default=262144, ge=16384, le=1048576)
    allowed_languages: list[Literal['python3', 'cpp', 'c', 'java']] = Field(
        default_factory=lambda: ['python3'], min_length=1, max_length=4)
    checker: Literal['TEXT_TRIM_TRAILING'] = 'TEXT_TRIM_TRAILING'
    cases: list[CaseInput] = Field(default_factory=list, max_length=200)

    @field_validator('allowed_languages')
    @classmethod
    def unique_languages(cls, value):
        if len(value) != len(set(value)):
            raise ValueError('Languages must be unique.')
        return value


class DimensionInput(Input):
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default='', max_length=8192)
    max_score: Decimal = Field(gt=0, le=999999, max_digits=8, decimal_places=2)


class RubricInput(Input):
    name: str = Field(default='评分量表', min_length=1, max_length=100)
    items: list[DimensionInput] = Field(default_factory=list, max_length=30)


class VersionInput(Input):
    title: str = Field(min_length=1, max_length=200)
    statement_md: str = Field(min_length=1, max_length=262144)
    answer_requirements_md: str | None = Field(default=None, max_length=65536)
    input_spec_md: str | None = Field(default=None, max_length=65536)
    output_spec_md: str | None = Field(default=None, max_length=65536)
    data_constraints_md: str | None = Field(default=None, max_length=65536)
    public_examples_md: str | None = Field(default=None, max_length=65536)
    difficulty_level: int = Field(default=3, ge=1, le=5)
    source_reference: str | None = Field(default=None, max_length=65536)
    knowledge_point_ids: list[DbId] = Field(default_factory=list, max_length=30)
    reference_solutions: list[ReferenceInput] = Field(default_factory=list, max_length=20)
    test_suite: SuiteInput | None = None
    rubric: RubricInput | None = None

    @field_validator('title', 'statement_md')
    @classmethod
    def meaningful_text(cls, value):
        if not value.strip() or '\x00' in value:
            raise ValueError('Nonempty text without NUL is required.')
        return value

    @model_validator(mode='after')
    def unique_tags_and_bounded_payload(self):
        if len(self.knowledge_point_ids) != len(set(self.knowledge_point_ids)):
            raise ValueError('Knowledge point IDs must be unique.')
        if len(self.model_dump_json().encode('utf-8')) > 4 * 1024 * 1024:
            raise ValueError('Problem configuration exceeds 4 MiB.')
        return self


class ProblemCreate(Input):
    code: str = Field(pattern=r'^[A-Za-z0-9][A-Za-z0-9_.-]{0,31}$')
    question_type: QuestionType
    version: VersionInput


class VersionUpdate(Input):
    expected_updated_at: datetime
    version: VersionInput

    @field_validator('expected_updated_at')
    @classmethod
    def timezone_required(cls, value):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError('Timestamp must include a timezone.')
        return value


class VersionAction(Input):
    expected_updated_at: datetime

    _timezone_required = field_validator('expected_updated_at')(VersionUpdate.timezone_required.__func__)


class VersionFork(Input):
    source_version_id: DbId


class KnowledgeCreate(Input):
    name: str = Field(min_length=1, max_length=100)

    @field_validator('name')
    @classmethod
    def trim_name(cls, value):
        if not value.strip() or '\x00' in value:
            raise ValueError('Name cannot be blank.')
        return value.strip()
