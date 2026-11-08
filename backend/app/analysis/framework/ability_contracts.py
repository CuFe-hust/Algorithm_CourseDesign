"""B0-specific versioned contracts; legacy learning contracts stay unchanged."""
from decimal import Decimal, localcontext
from typing import Annotated, Literal

from pydantic import Field, model_validator

from .contracts import Contract, Nonnegative, Ratio

Nonempty = Annotated[str, Field(strict=True, min_length=1, pattern=r'\S')]
ItemType = Literal['PROGRAMMING', 'SUBJECTIVE', 'ALGORITHM_ANALYSIS', 'OPEN_QUESTION', 'PROOF']
SourceKind = Literal['DATABASE', 'SYNTHETIC_FIXTURE', 'DEMO']
CHAPTER_NAMES = ('贪心算法', '分治算法', '动态规划', '图论', '搜索与回溯', '字符串', '排序与查找', '数据结构', '数学与数论', '位运算与杂项', '数组与模拟')


class AbilityExpectedPair(Contract):
    student_key: Nonempty
    item_key: Nonempty
    state: Literal['SCORED', 'PENDING', 'NOT_SUBMITTED', 'INVALID']


class AbilityScope(Contract):
    scope_kind: Literal['COURSE'] = 'COURSE'
    scope_label: Nonempty
    student_keys: list[Nonempty]
    assignment_ids: list[Nonempty]
    expected_pairs: list[AbilityExpectedPair]


class AbilityChapter(Contract):
    order: int = Field(ge=1, le=11)
    code: Nonempty
    name: Nonempty


class AbilityItem(Contract):
    item_key: Nonempty
    item_code: Nonempty
    item_version: Nonempty
    item_type: ItemType
    difficulty: int = Field(ge=1, le=5)
    max_score: Decimal = Field(gt=0, allow_inf_nan=False)
    chapter_weights: dict[str, Ratio]


class AbilityGrade(Contract):
    student_key: Nonempty
    item_key: Nonempty
    normalized_score: Ratio
    score_version: Nonempty
    result_ref: Nonempty
    score_kind: Nonempty


class AbilityParameters(Contract):
    method: Literal['B0'] = 'B0'
    min_items: int = Field(default=3, ge=1)
    min_coverage_items: Ratio = Decimal('0.5')
    merge_policy: Literal['CHAPTER_WEIGHT'] = 'CHAPTER_WEIGHT'
    include_unmapped: Literal[False] = False
    interval_policy: Literal['NONE'] = 'NONE'


class AbilityInputV2(Contract):
    contract_version: Literal['ability-b0-v1'] = 'ability-b0-v1'
    source_kind: SourceKind
    results_snapshot_version: Nonempty
    scoring_policy_version: Nonempty
    chapter_taxonomy_version: Nonempty
    chapter_mapping_version: Nonempty
    scope: AbilityScope
    chapter_taxonomy: list[AbilityChapter]
    items: list[AbilityItem]
    grades: list[AbilityGrade]
    parameters: AbilityParameters = Field(default_factory=AbilityParameters)

    @model_validator(mode='after')
    def validate_snapshot(self):
        expected = {(i+1, f'CH{i+1:02}', n) for i,n in enumerate(CHAPTER_NAMES)}
        if len(self.chapter_taxonomy) != 11 or {(c.order,c.code,c.name) for c in self.chapter_taxonomy} != expected:
            raise ValueError('INVALID_CHAPTER_TAXONOMY')
        for name, values in [('student_keys', self.scope.student_keys), ('assignment_ids', self.scope.assignment_ids), ('item_keys', [i.item_key for i in self.items])]:
            if len(values) != len(set(values)):
                raise ValueError(f'DUPLICATE_{name.upper()}')
        codes = {c.code for c in self.chapter_taxonomy}
        items = {i.item_key: i for i in self.items}
        for item in self.items:
            weights = item.chapter_weights
            if set(weights)-codes or any(w <= 0 for w in weights.values()):
                raise ValueError('INVALID_CHAPTER_WEIGHTS')
            with localcontext() as ctx:
                ctx.prec = 28
                if weights and abs(sum(weights.values(), Decimal(0))-1) > Decimal('0.000001'):
                    raise ValueError('INVALID_CHAPTER_WEIGHT_SUM')
        students = set(self.scope.student_keys)
        pairs = {}
        for pair in self.scope.expected_pairs:
            key = pair.student_key, pair.item_key
            if key in pairs:
                raise ValueError('DUPLICATE_EXPECTED_PAIR')
            if pair.student_key not in students or pair.item_key not in items:
                raise ValueError('PAIR_OUTSIDE_SCOPE')
            pairs[key] = pair.state
        grades = {}
        for grade in self.grades:
            key = grade.student_key, grade.item_key
            if pairs.get(key) != 'SCORED':
                raise ValueError('GRADE_OUTSIDE_SCORED_SCOPE')
            if key in grades and grades[key] != grade:
                raise ValueError('DUPLICATE_SCORE_CONFLICT')
            grades[key] = grade
        if any(state == 'SCORED' and key not in grades for key,state in pairs.items()):
            raise ValueError('SCORED_MISSING_GRADE')
        return self


class AbilityMissing(Contract):
    pending: int = Field(default=0, ge=0)
    not_submitted: int = Field(default=0, ge=0)
    invalid: int = Field(default=0, ge=0)


class AbilityTypeEstimate(Contract):
    value: Ratio
    n_items: int = Field(ge=1)
    W_sum: Nonnegative


class AbilityEstimate(Contract):
    object_key: Nonempty
    dimension: Nonempty
    dimension_label: Nonempty
    dimension_order: int = Field(ge=1, le=11)
    value: Ratio | None
    status: Literal['NOT_COVERED', 'NO_EVIDENCE', 'LOW_EVIDENCE', 'OK']
    assigned_items: int = Field(ge=0)
    scored_items: int = Field(ge=0)
    n_items: int = Field(ge=0)
    W_sum: Nonnegative
    W_assigned: Nonnegative
    n_eff: Nonnegative
    coverage_items: Ratio | None
    coverage_weight: Ratio | None
    missing: AbilityMissing
    observed_min: Ratio | None
    observed_max: Ratio | None
    diagnostic_flags: list[str]
    by_type: dict[Literal['PROGRAMMING', 'SUBJECTIVE'], AbilityTypeEstimate]
    evidence_item_keys: list[Nonempty]


class AbilityDiagnostics(Contract):
    method: Literal['B0'] = 'B0'
    merge_policy: Literal['CHAPTER_WEIGHT'] = 'CHAPTER_WEIGHT'
    min_items: int = Field(ge=1)
    min_coverage_items: Ratio
    unmapped_item_count: int = Field(ge=0)
    warnings: list[str]


class AbilityOutputV2(Contract):
    contract_version: Literal['ability-b0-v1'] = 'ability-b0-v1'
    implementation_version: Literal['2'] = '2'
    source_kind: SourceKind
    results_snapshot_version: Nonempty
    scoring_policy_version: Nonempty
    chapter_taxonomy_version: Nonempty
    chapter_mapping_version: Nonempty
    estimates: list[AbilityEstimate]
    diagnostics: AbilityDiagnostics
