"""Versioned pure data contracts. No Web or database dependencies."""
import hashlib
import json
from decimal import Decimal
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, StrictStr

Key = StrictStr
Ratio = Annotated[Decimal, Field(ge=0, le=1, allow_inf_nan=False)]
Nonnegative = Annotated[Decimal, Field(ge=0, allow_inf_nan=False)]


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
        separators=(',', ':'), allow_nan=False).encode()).hexdigest()


class Contract(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Edge(Contract):
    answer_key: Key
    reviewer_key: Key


class Answer(Contract):
    answer_key: Key
    author_key: Key


class AllocationInput(Contract):
    answers: list[Answer]
    reviewers: list[Key]
    required_reviewers: int = Field(ge=1, le=10)
    forbidden_edges: list[Edge] = Field(default_factory=list)
    existing_edges: list[Edge] = Field(default_factory=list)
    history: list[Edge] = Field(default_factory=list)
    required_by_answer: dict[Key, Annotated[int, Field(ge=1, le=10)]] = Field(default_factory=dict)
    prior_loads: dict[Key, Annotated[int, Field(ge=0)]] = Field(default_factory=dict)
    max_tasks_per_reviewer: int | None = Field(default=None, ge=1, le=3000)
    seed: int = 0


class AllocationOutput(Contract):
    feasible: bool
    edges: list[Edge]
    unmet_constraints: list[str]
    load_metrics: dict[str, int]


class Evaluation(Contract):
    evaluation_key: Key
    answer_key: Key
    reviewer_key: Key | None = None
    score: Nonnegative
    weight: Nonnegative = Decimal(1)


class AggregationInput(Contract):
    answers: list[Key]
    rubric_max: Decimal = Field(gt=0, allow_inf_nan=False)
    minimum_samples: int = Field(default=2, ge=1)
    evaluations: list[Evaluation]
    method: Literal['weighted_mean', 'weighted_median'] = 'weighted_mean'


class AggregatedScore(Contract):
    answer_key: Key
    normalized_score: Ratio | None
    valid_count: int = Field(ge=0)
    dispersion: Nonnegative | None
    reason: str | None


class AggregationOutput(Contract):
    scores: list[AggregatedScore]


class Content(Contract):
    answer_key: Key
    content: str
    language: str | None = None
    item_key: Key | None = None


class ContentInput(Contract):
    answers: list[Content]
    templates: list[str] = Field(default_factory=list)
    comparison_scope: str = 'SAME_ITEM'
    threshold: Ratio = Decimal('0.5')
    minimum_tokens: int = Field(default=40, ge=1)


class SimilarPair(Contract):
    left_key: Key
    right_key: Key
    similarity: Ratio
    matching_spans: list[dict[str, int]] = Field(default_factory=list)
    # Both directions of containment are stored: a short submission copied into
    # a long one scores high in one direction only, which is exactly the
    # pattern a teacher needs to see.
    containment_left: Ratio | None = None
    containment_right: Ratio | None = None
    jaccard: Ratio | None = None
    shared_fingerprints: int | None = Field(default=None, ge=0)
    left_fingerprints: int | None = Field(default=None, ge=0)
    right_fingerprints: int | None = Field(default=None, ge=0)
    # Token counts per side: evidence strength depends on program length.
    left_tokens: int | None = Field(default=None, ge=0)
    right_tokens: int | None = Field(default=None, ge=0)
    matched_tokens: int | None = Field(default=None, ge=0)
    longest_run_tokens: int | None = Field(default=None, ge=0)


class SimilarCluster(Contract):
    member_keys: list[Key]
    size: int = Field(ge=3)
    max_similarity: Ratio
    # A cluster is a connected component, not a clique. These three fields let a
    # reader see the difference: "2 of 3 pairs qualify" is a chain, not a group
    # of mutual copies.
    min_similarity: Ratio | None = None
    qualifying_pairs: int | None = Field(default=None, ge=0)
    total_pairs: int | None = Field(default=None, ge=0)


class SkippedSubmission(Contract):
    answer_key: Key
    reason: Literal['INSUFFICIENT_TOKENS', 'NOT_A_PROGRAMMING_LANGUAGE', 'TOKENIZATION_FAILED']
    tokens: int = Field(ge=0)
    detail: str | None = None


class SimilarityOutput(Contract):
    pairs: list[SimilarPair]
    method: str
    clusters: list[SimilarCluster] = Field(default_factory=list)
    insufficient: list[SkippedSubmission] = Field(default_factory=list)
    submission_count: int = Field(default=0, ge=0)
    parameters: dict[str, str | int | float] = Field(default_factory=dict)
    # Stated so a teacher never reads a cut list as a complete one.
    pairs_truncated: bool = False


class Evidence(Contract):
    object_key: Key
    kind: str
    value: Nonnegative | None = None
    explanation: str


class SignalOutput(Contract):
    signals: list[Evidence]
    sample_count: int = Field(ge=0)
    missing_count: int = Field(ge=0)


class DetectionInput(Contract):
    evaluations: list[Evaluation]
    baseline: list[AggregatedScore]
    history: list[Evaluation] = Field(default_factory=list)
    edges: list[Edge] = Field(default_factory=list)
    minimum_samples: int = Field(default=2, ge=1)
    threshold: Ratio = Decimal('0.2')
    rubric_max: Decimal = Field(default=Decimal('100'), gt=0, allow_inf_nan=False)
    history_baseline: list[AggregatedScore] = Field(default_factory=list)
    author_map: dict[Key, Key] = Field(default_factory=dict)


class Timing(Contract):
    task_key: Key
    elapsed_seconds: Nonnegative | None


class TimingInput(Contract):
    timings: list[Timing]
    minimum_samples: int = Field(default=2, ge=1)
    short_seconds: Nonnegative = Decimal('15')
    relative_fraction: Ratio = Decimal('0.2')


class Grade(Contract):
    student_key: Key
    item_key: Key
    normalized_score: Ratio | None
    knowledge_weights: dict[str, Ratio] = Field(default_factory=dict)
    difficulty: int = Field(default=3, ge=1, le=5)


class LearningInput(Contract):
    results_snapshot_version: Key
    grades: list[Grade]
    minimum_samples: int = Field(default=2, ge=1)


class Estimate(Contract):
    object_key: Key
    dimension: str
    value: Ratio | None
    sample_count: int = Field(ge=0)
    missing_count: int = Field(ge=0)


class LearningOutput(Contract):
    estimates: list[Estimate]


class Event(Contract):
    student_key: Key
    kind: str
    occurred_at: str


class BehaviorInput(Contract):
    events: list[Event]
    available_event_types: list[str]
    time_range: dict[str, str]


class BehaviorOutput(Contract):
    counts: dict[str, int]
    available_event_types: list[str]
    limitations: list[str]


class StatisticsInput(Contract):
    roster: list[Key]
    submitted: list[Key]
    grades: list[Grade]
    results_snapshot_version: Key | None = None


class StatisticsOutput(Contract):
    denominator: int = Field(ge=0)
    submitted_count: int = Field(ge=0)
    completed_count: int = Field(ge=0)
    missing_count: int = Field(ge=0)
    mean_score: Ratio | None


class JudgeSummary(Contract):
    student_key: Key
    submission_key: Key
    passed_cases: int | None = Field(default=None, ge=0)
    total_cases: int | None = Field(default=None, gt=0)
    verdict: str
    execution_mode: str
    runtime_profile: str | None = None
    is_mock: bool


class JudgeInput(Contract):
    results: list[JudgeSummary]
    test_suite_key: Key | None
    evaluation_context: dict[str, str]


class JudgeOutput(Contract):
    results: list[JudgeSummary]
    score_available: bool = False
    reason: str


class AlgorithmOutput(Contract):
    schema_version: Literal['analysis-v2'] = 'analysis-v2'
    algorithm_key: str
    implementation_name: str
    implementation_version: str = '1'
    input_hash: str
    is_mock: bool
    status: Literal['OK', 'INSUFFICIENT_DATA', 'INFEASIBLE', 'NOT_IMPLEMENTED']
    payload: dict
    evidence: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
