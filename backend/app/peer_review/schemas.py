"""Strict real-business DTOs. Client identities, time and aggregate results are not accepted."""
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal
from pydantic import Field, StrictBool, StrictInt, StrictStr, field_validator, model_validator
from app.analysis.framework.contracts import Contract

Id = Annotated[int, Field(gt=0, le=9223372036854775807)]
Ratio = Annotated[Decimal, Field(ge=0, le=1, max_digits=8, decimal_places=6, allow_inf_nan=False)]
Score = Annotated[Decimal, Field(ge=0, le=99999999, max_digits=10, decimal_places=2, allow_inf_nan=False)]


class Input(Contract):
    @field_validator('*', mode='before')
    @classmethod
    def no_nul(cls, value):
        if isinstance(value, str) and '\x00' in value:
            raise ValueError('NUL is not allowed')
        return value


class Command(Input):
    request_id: StrictStr = Field(min_length=1, max_length=64, pattern=r'^[A-Za-z0-9_.:-]+$')


class VersionCommand(Command):
    expected_revision: StrictInt = Field(ge=0)


class ReasonCommand(VersionCommand):
    reason: str = Field(min_length=1, max_length=2000)

    @field_validator('reason')
    @classmethod
    def nonempty(cls, value):
        if not value.strip():
            raise ValueError('A nonempty reason is required')
        return value.strip()


class Policy(Input):
    schema_version: Literal['peer-review-v1'] = 'peer-review-v1'
    aggregation_method: Literal['weighted_mean', 'weighted_median'] = 'weighted_mean'
    minimum_samples: StrictInt = Field(default=2, ge=1, le=10)
    deviation_threshold: Ratio = Decimal('0.2')
    deviation_minimum_peers: StrictInt = Field(default=2, ge=2, le=10)
    bias_threshold: Ratio = Decimal('0.15')
    history_minimum_samples: StrictInt = Field(default=3, ge=3, le=100)
    short_seconds: Decimal = Field(default=Decimal('15'), ge=0, le=600, decimal_places=3, allow_inf_nan=False)
    timing_relative_fraction: Ratio = Decimal('0.2')
    timing_minimum_samples: StrictInt = Field(default=5, ge=3, le=100)
    seed: StrictInt = Field(default=20261027, ge=-2147483648, le=2147483647)
    max_tasks_per_reviewer: StrictInt | None = Field(default=None, ge=1, le=2000)


class ForbiddenPair(Input):
    student_a_id: Id
    student_b_id: Id

    @model_validator(mode='after')
    def distinct(self):
        if self.student_a_id == self.student_b_id:
            raise ValueError('Use two different students')
        return self


class Preview(Command):
    review_deadline: datetime
    policy: Policy = Field(default_factory=Policy)
    forbidden_pairs: list[ForbiddenPair] = Field(default_factory=list, max_length=1000)
    reason: str = Field(default='初次互评分配预览', min_length=1, max_length=2000)

    @field_validator('review_deadline')
    @classmethod
    def timezone_required(cls, value):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError('Timezone required')
        return value


class Publish(VersionCommand):
    expected_source_hash: str = Field(pattern=r'^[a-f0-9]{64}$')


class Deadline(ReasonCommand):
    review_deadline: datetime
    _aware = field_validator('review_deadline')(Preview.timezone_required.__func__)


class Close(ReasonCommand):
    accept_incomplete: StrictBool = False


class DimensionScore(Input):
    rubric_item_id: Id
    score: Score


class EvaluationInput(Input):
    client_request_id: StrictStr = Field(min_length=1, max_length=64, pattern=r'^[A-Za-z0-9_.:-]+$')
    scores: list[DimensionScore] = Field(min_length=1, max_length=30)
    comment: str = Field(min_length=1, max_length=8192)

    @field_validator('comment')
    @classmethod
    def meaningful_comment(cls, value):
        if not value.strip():
            raise ValueError('Comment is required')
        return value.strip()

    @model_validator(mode='after')
    def unique_dimensions(self):
        if len({s.rubric_item_id for s in self.scores}) != len(self.scores):
            raise ValueError('Repeated rubric dimension')
        return self


class DecisionInput(Input):
    action: Literal['KEEP', 'DOWNWEIGHT', 'INVALIDATE', 'OVERRIDE']
    evaluation_id: Id | None = None
    answer_key: str | None = Field(default=None, min_length=1, max_length=64)
    weight: Ratio | None = None
    override_score: Score | None = None
    reason: str = Field(min_length=1, max_length=2000)

    @model_validator(mode='after')
    def shape(self):
        if (self.evaluation_id is None) == (self.answer_key is None) or not self.reason.strip():
            raise ValueError('Exactly one target and a nonempty reason are required')
        if self.action in ('DOWNWEIGHT','INVALIDATE') and self.evaluation_id is None:
            raise ValueError('This action requires an evaluation')
        if self.action == 'DOWNWEIGHT':
            if self.weight is None or self.weight <= 0:
                raise ValueError('Weight must be positive')
        elif self.weight is not None:
            raise ValueError('Weight is only used by DOWNWEIGHT')
        if self.action == 'OVERRIDE':
            if self.answer_key is None or self.override_score is None:
                raise ValueError('Override requires an answer and score')
        elif self.override_score is not None:
            raise ValueError('Unexpected override score')
        return self


class Resolve(ReasonCommand):
    expected_source_hash: str = Field(pattern=r'^[a-f0-9]{64}$')
    acknowledged_statuses: dict[str, Literal['OK','INSUFFICIENT_DATA','NOT_IMPLEMENTED']] = Field(min_length=4,max_length=4)
    decisions: list[DecisionInput] = Field(default_factory=list, max_length=2000)
    request_supplement: StrictBool = False
    supplement_deadline: datetime | None = None

    @field_validator('supplement_deadline')
    @classmethod
    def optional_aware(cls, value):
        return Preview.timezone_required(value) if value is not None else value

    @model_validator(mode='after')
    def unique_targets(self):
        keys=[('evaluation',d.evaluation_id) if d.evaluation_id else ('answer',d.answer_key) for d in self.decisions]
        if len(keys)!=len(set(keys)):
            raise ValueError('Duplicate or conflicting decisions for a target')
        if self.request_supplement and self.supplement_deadline is None:
            raise ValueError('A supplement deadline is required')
        return self
